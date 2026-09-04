import { deepEqual as equal } from 'fast-equals'

import { formatPropertyLabel } from 'lib/components/PropertyFilters/utils'
import { dateFilterToText } from 'lib/utils/dateFilters'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import type { DashboardFilter, HogQLVariable, MultipleBreakdownType } from '~/queries/schema/schema-general'
import type { AnyPropertyFilter, BreakdownType } from '~/types'

export interface DashboardSettingsChange {
    label: string
    previousValue: string[]
    value: string[]
    status: 'new' | 'changed' | 'removed'
}

export type DashboardFilterChange = DashboardSettingsChange

function formatVariableValue(variable: { isNull?: boolean; value?: unknown } | undefined): string[] {
    if (variable?.isNull) {
        // SQL NULL is an explicit value in the changes UI. An empty array represents an unset variable.
        return ['null']
    }
    if (variable?.value == null) {
        return []
    }
    return [String(variable.value)]
}

export function dashboardVariableValuesEqual(
    previous: { isNull?: boolean; value?: unknown } | undefined,
    current: { isNull?: boolean; value?: unknown } | undefined
): boolean {
    return equal(formatVariableValue(previous), formatVariableValue(current))
}

/**
 * Deep equality that reads null and an absent key as the same setting. Both mean "inherit" for a
 * dashboard filter, and the inherit option on each control writes null rather than dropping the key.
 */
function dashboardFilterValuesEqual(previous: unknown, current: unknown): boolean {
    if (previous == null && current == null) {
        return true
    }
    return equal(previous, current)
}

export function dashboardFiltersEqual(previous: DashboardFilter, current: DashboardFilter): boolean {
    // Property filters are compared with the same rule that builds the change list, so the unsaved
    // count can never disagree with what the change list can show. A reordered AND list holds the
    // same filters, so it is not a change.
    if (getPropertyFilterChanges(previous, current).length > 0) {
        return false
    }

    const keys = new Set([...Object.keys(previous), ...Object.keys(current)])
    return Array.from(keys).every(
        (key) =>
            key === 'properties' ||
            dashboardFilterValuesEqual(
                (previous as Record<string, unknown>)[key],
                (current as Record<string, unknown>)[key]
            )
    )
}

function changeValue(value: string | undefined): string[] {
    return value ? [value] : []
}

export function getDashboardVariableChanges(
    previousVariables: Record<string, HogQLVariable>,
    currentVariables: Record<string, HogQLVariable>,
    defaultVariables: Record<string, HogQLVariable>
): DashboardSettingsChange[] {
    const variableIds = new Set([...Object.keys(previousVariables), ...Object.keys(currentVariables)])

    return Array.from(variableIds).flatMap((variableId) => {
        const previous = previousVariables[variableId] ?? defaultVariables[variableId]
        const current = currentVariables[variableId] ?? defaultVariables[variableId]
        if (dashboardVariableValuesEqual(previous, current)) {
            return []
        }

        return [
            {
                label: current?.code_name ?? previous?.code_name ?? variableId,
                previousValue: formatVariableValue(previous),
                value: formatVariableValue(current),
                status: getChangeStatus(!!previous, !!current),
            },
        ]
    })
}

function propertyIdentity(property: AnyPropertyFilter): string {
    if (!('key' in property)) {
        return JSON.stringify(property)
    }

    return JSON.stringify({
        key: property.key,
        type: property.type,
        group_type_index: 'group_type_index' in property ? property.group_type_index : undefined,
    })
}

function formatDateRange(filters: DashboardFilter): string {
    const dateRange = dateFilterToText(filters.date_from, filters.date_to, 'All time') || 'All time'
    // explicitDate moves the period boundaries to the current time, so a flip of the "Exact time
    // range" switch alone has to read as a change rather than as the same range twice.
    return filters.explicitDate ? `${dateRange} (exact time range)` : dateRange
}

const BREAKDOWN_TYPE_LABELS: Record<BreakdownType | MultipleBreakdownType, string> = {
    cohort: 'cohort',
    person: 'person property',
    event: 'event property',
    event_metadata: 'event metadata',
    group: 'group property',
    session: 'session property',
    hogql: 'SQL expression',
    data_warehouse: 'data warehouse property',
    data_warehouse_person_property: 'data warehouse person property',
    revenue_analytics: 'revenue analytics property',
}

// The same property name exists in several taxonomies, so a breakdown that keeps the name and
// changes the taxonomy would otherwise read as the same value on both sides of the change.
function formatBreakdownValue(
    property: unknown,
    type: BreakdownType | MultipleBreakdownType | null | undefined
): string {
    const name = String(property)
    const label = type ? BREAKDOWN_TYPE_LABELS[type] : undefined
    return label ? `${name} (${label})` : name
}

function formatBreakdown(filters: DashboardFilter): string[] {
    const { breakdown_filter } = filters
    if (!breakdown_filter?.breakdown && !breakdown_filter?.breakdowns?.length) {
        return []
    }

    if (breakdown_filter.breakdowns?.length) {
        return breakdown_filter.breakdowns.map((breakdown) => formatBreakdownValue(breakdown.property, breakdown.type))
    }

    if (Array.isArray(breakdown_filter.breakdown)) {
        return breakdown_filter.breakdown.map((breakdown) =>
            formatBreakdownValue(breakdown, breakdown_filter.breakdown_type)
        )
    }
    return [formatBreakdownValue(breakdown_filter.breakdown, breakdown_filter.breakdown_type)]
}

function formatTestAccounts(filterTestAccounts: DashboardFilter['filterTestAccounts']): string {
    if (filterTestAccounts === null || filterTestAccounts === undefined) {
        return 'Default'
    }
    // A true filterTestAccounts filters internal and test users out.
    return filterTestAccounts ? 'Excluded' : 'Included'
}

function getChangeStatus(previousExists: boolean, currentExists: boolean): DashboardFilterChange['status'] {
    if (!previousExists) {
        return 'new'
    }
    if (!currentExists) {
        return 'removed'
    }
    return 'changed'
}

function getPropertyChanges(previous: AnyPropertyFilter[], current: AnyPropertyFilter[]): DashboardFilterChange[] {
    const unmatchedPrevious = [...previous]
    const changes: DashboardFilterChange[] = []

    current.forEach((property) => {
        const previousIndex = unmatchedPrevious.findIndex(
            (previousProperty) => propertyIdentity(previousProperty) === propertyIdentity(property)
        )

        if (previousIndex === -1) {
            changes.push({
                label: 'Property filter',
                previousValue: [],
                value: [formatPropertyLabel(property, {}).trim()],
                status: 'new',
            })
            return
        }

        const previousProperty = unmatchedPrevious.splice(previousIndex, 1)[0]
        if (!equal(previousProperty, property)) {
            changes.push({
                label: 'Property filter',
                previousValue: [formatPropertyLabel(previousProperty, {}).trim()],
                value: [formatPropertyLabel(property, {}).trim()],
                status: 'changed',
            })
        }
    })

    unmatchedPrevious.forEach((property) => {
        changes.push({
            label: 'Property filter',
            previousValue: [formatPropertyLabel(property, {}).trim()],
            value: [],
            status: 'removed',
        })
    })

    return changes
}

function getPropertyFilterChanges(
    previousFilters: DashboardFilter,
    currentFilters: DashboardFilter
): DashboardFilterChange[] {
    const previousProperties = previousFilters.properties ?? []
    const currentProperties = currentFilters.properties ?? []
    const changes = getPropertyChanges(previousProperties, currentProperties)
    const previousPropertiesAreExplicit = previousFilters.properties != null
    const currentPropertiesAreExplicit = currentFilters.properties != null
    if (
        !changes.length &&
        previousPropertiesAreExplicit !== currentPropertiesAreExplicit &&
        (previousProperties.length === 0 || currentProperties.length === 0)
    ) {
        changes.push({
            label: 'Property filters',
            previousValue: previousPropertiesAreExplicit ? ['No property filters'] : [],
            value: currentPropertiesAreExplicit ? ['No property filters'] : [],
            status: getChangeStatus(previousPropertiesAreExplicit, currentPropertiesAreExplicit),
        })
    }

    return changes
}

export function getDashboardFilterChanges(
    previousFilters: DashboardFilter,
    currentFilters: DashboardFilter
): DashboardFilterChange[] {
    const changes = getPropertyFilterChanges(previousFilters, currentFilters)
    const previousHasDate = !!previousFilters.date_from || !!previousFilters.date_to || !!previousFilters.explicitDate
    const currentHasDate = !!currentFilters.date_from || !!currentFilters.date_to || !!currentFilters.explicitDate

    if (
        !dashboardFilterValuesEqual(previousFilters.date_from, currentFilters.date_from) ||
        !dashboardFilterValuesEqual(previousFilters.date_to, currentFilters.date_to) ||
        !dashboardFilterValuesEqual(previousFilters.explicitDate, currentFilters.explicitDate)
    ) {
        changes.push({
            label: 'Date range',
            previousValue: previousHasDate ? [formatDateRange(previousFilters)] : [],
            value: currentHasDate ? [formatDateRange(currentFilters)] : [],
            status: getChangeStatus(previousHasDate, currentHasDate),
        })
    }

    if (!dashboardFilterValuesEqual(previousFilters.interval, currentFilters.interval)) {
        changes.push({
            label: 'Grouped by',
            previousValue: changeValue(
                previousFilters.interval ? capitalizeFirstLetter(previousFilters.interval) : undefined
            ),
            value: changeValue(currentFilters.interval ? capitalizeFirstLetter(currentFilters.interval) : undefined),
            status: getChangeStatus(!!previousFilters.interval, !!currentFilters.interval),
        })
    }

    if (!dashboardFilterValuesEqual(previousFilters.breakdown_filter, currentFilters.breakdown_filter)) {
        const previousHasBreakdown =
            !!previousFilters.breakdown_filter?.breakdown || !!previousFilters.breakdown_filter?.breakdowns?.length
        const currentHasBreakdown =
            !!currentFilters.breakdown_filter?.breakdown || !!currentFilters.breakdown_filter?.breakdowns?.length
        changes.push({
            label: 'Breakdown by',
            previousValue: previousHasBreakdown ? formatBreakdown(previousFilters) : [],
            value: currentHasBreakdown ? formatBreakdown(currentFilters) : [],
            status: getChangeStatus(previousHasBreakdown, currentHasBreakdown),
        })
    }

    if (!dashboardFilterValuesEqual(previousFilters.filterTestAccounts, currentFilters.filterTestAccounts)) {
        const previousHasTestAccountSetting =
            previousFilters.filterTestAccounts !== null && previousFilters.filterTestAccounts !== undefined
        const currentHasTestAccountSetting =
            currentFilters.filterTestAccounts !== null && currentFilters.filterTestAccounts !== undefined
        changes.push({
            label: 'Test accounts',
            previousValue: previousHasTestAccountSetting
                ? [formatTestAccounts(previousFilters.filterTestAccounts)]
                : [],
            value: currentHasTestAccountSetting ? [formatTestAccounts(currentFilters.filterTestAccounts)] : [],
            status: getChangeStatus(previousHasTestAccountSetting, currentHasTestAccountSetting),
        })
    }

    return changes
}
