import { deepEqual as equal } from 'fast-equals'

import { formatPropertyLabel } from 'lib/components/PropertyFilters/utils'
import { dateFilterToText } from 'lib/utils/dateFilters'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import type { DashboardFilter } from '~/queries/schema/schema-general'
import type { AnyPropertyFilter } from '~/types'

export interface DashboardFilterChange {
    label: string
    previousValue?: string | string[]
    value?: string | string[]
    status: 'new' | 'changed' | 'removed'
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
    return dateFilterToText(filters.date_from, filters.date_to, 'All time') || 'All time'
}

function formatBreakdown(filters: DashboardFilter): string | string[] {
    const { breakdown_filter } = filters
    if (!breakdown_filter?.breakdown && !breakdown_filter?.breakdowns?.length) {
        return 'None'
    }

    if (breakdown_filter.breakdowns?.length) {
        return breakdown_filter.breakdowns.map((breakdown) => String(breakdown.property))
    }

    return Array.isArray(breakdown_filter.breakdown)
        ? breakdown_filter.breakdown.map(String)
        : String(breakdown_filter.breakdown)
}

function formatTestAccounts(filterTestAccounts: DashboardFilter['filterTestAccounts']): string {
    if (filterTestAccounts === null || filterTestAccounts === undefined) {
        return 'Default'
    }
    return filterTestAccounts ? 'Included' : 'Excluded'
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
            changes.push({ label: 'Property filter', value: formatPropertyLabel(property, {}).trim(), status: 'new' })
            return
        }

        const previousProperty = unmatchedPrevious.splice(previousIndex, 1)[0]
        if (!equal(previousProperty, property)) {
            changes.push({
                label: 'Property filter',
                previousValue: formatPropertyLabel(previousProperty, {}).trim(),
                value: formatPropertyLabel(property, {}).trim(),
                status: 'changed',
            })
        }
    })

    unmatchedPrevious.forEach((property) => {
        changes.push({
            label: 'Property filter',
            previousValue: formatPropertyLabel(property, {}).trim(),
            status: 'removed',
        })
    })

    return changes
}

export function getDashboardFilterChanges(
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
            previousValue: previousPropertiesAreExplicit ? 'No property filters' : undefined,
            value: currentPropertiesAreExplicit ? 'No property filters' : undefined,
            status: getChangeStatus(previousPropertiesAreExplicit, currentPropertiesAreExplicit),
        })
    }
    const previousHasDate = !!previousFilters.date_from || !!previousFilters.date_to
    const currentHasDate = !!currentFilters.date_from || !!currentFilters.date_to

    if (
        !equal(
            {
                date_from: previousFilters.date_from,
                date_to: previousFilters.date_to,
                explicitDate: previousFilters.explicitDate,
            },
            {
                date_from: currentFilters.date_from,
                date_to: currentFilters.date_to,
                explicitDate: currentFilters.explicitDate,
            }
        )
    ) {
        changes.push({
            label: 'Date range',
            previousValue: previousHasDate ? formatDateRange(previousFilters) : undefined,
            value: currentHasDate ? formatDateRange(currentFilters) : undefined,
            status: getChangeStatus(previousHasDate, currentHasDate),
        })
    }

    if (!equal(previousFilters.interval, currentFilters.interval)) {
        changes.push({
            label: 'Grouped by',
            previousValue: previousFilters.interval ? capitalizeFirstLetter(previousFilters.interval) : undefined,
            value: currentFilters.interval ? capitalizeFirstLetter(currentFilters.interval) : undefined,
            status: getChangeStatus(!!previousFilters.interval, !!currentFilters.interval),
        })
    }

    if (!equal(previousFilters.breakdown_filter, currentFilters.breakdown_filter)) {
        const previousHasBreakdown =
            !!previousFilters.breakdown_filter?.breakdown || !!previousFilters.breakdown_filter?.breakdowns?.length
        const currentHasBreakdown =
            !!currentFilters.breakdown_filter?.breakdown || !!currentFilters.breakdown_filter?.breakdowns?.length
        changes.push({
            label: 'Breakdown by',
            previousValue: previousHasBreakdown ? formatBreakdown(previousFilters) : undefined,
            value: currentHasBreakdown ? formatBreakdown(currentFilters) : undefined,
            status: getChangeStatus(previousHasBreakdown, currentHasBreakdown),
        })
    }

    if (!equal(previousFilters.filterTestAccounts, currentFilters.filterTestAccounts)) {
        const previousHasTestAccountSetting =
            previousFilters.filterTestAccounts !== null && previousFilters.filterTestAccounts !== undefined
        const currentHasTestAccountSetting =
            currentFilters.filterTestAccounts !== null && currentFilters.filterTestAccounts !== undefined
        changes.push({
            label: 'Test accounts',
            previousValue: previousHasTestAccountSetting
                ? formatTestAccounts(previousFilters.filterTestAccounts)
                : undefined,
            value: currentHasTestAccountSetting ? formatTestAccounts(currentFilters.filterTestAccounts) : undefined,
            status: getChangeStatus(previousHasTestAccountSetting, currentHasTestAccountSetting),
        })
    }

    return changes
}
