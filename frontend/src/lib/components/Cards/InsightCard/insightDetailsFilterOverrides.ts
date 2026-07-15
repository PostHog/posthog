import { DashboardFilter, TileFilters } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, InsightFilterOverrideContext, PropertyGroupFilter } from '~/types'

export type OverrideSource = 'dashboard' | 'tile'

export interface EffectiveFilterOverrides {
    propertyGroups: { properties: AnyPropertyFilter[]; source: OverrideSource }[]
    overriddenByTile: AnyPropertyFilter[]
    breakdown: { breakdownFilter: NonNullable<DashboardFilter['breakdown_filter']>; source: OverrideSource } | null
}

export function getEffectiveFilterOverrides(
    filterOverrideContext: InsightFilterOverrideContext | null | undefined,
    filtersOverride: DashboardFilter | undefined,
    tileFiltersOverride: TileFilters | null | undefined
): EffectiveFilterOverrides {
    const dashboardFilters = filterOverrideContext ? filterOverrideContext.dashboard : filtersOverride
    const tileFilters = filterOverrideContext ? filterOverrideContext.tile : tileFiltersOverride
    const dashboardProperties = (dashboardFilters?.properties ?? []) as AnyPropertyFilter[]
    const tileProperties = (tileFilters?.properties ?? []) as AnyPropertyFilter[]
    const overriddenByTile = (filterOverrideContext?.overridden_dashboard?.properties ?? []) as AnyPropertyFilter[]
    const propertyGroups: EffectiveFilterOverrides['propertyGroups'] = []
    if (dashboardProperties.length > 0) {
        propertyGroups.push({ properties: dashboardProperties, source: 'dashboard' })
    }
    if (tileProperties.length > 0) {
        propertyGroups.push({ properties: tileProperties, source: 'tile' })
    }

    const tileBreakdown = tileFilters?.breakdown_filter as DashboardFilter['breakdown_filter']
    const dashboardBreakdown = dashboardFilters?.breakdown_filter as DashboardFilter['breakdown_filter']
    const breakdown = tileBreakdown
        ? { breakdownFilter: tileBreakdown, source: 'tile' as const }
        : dashboardBreakdown
          ? { breakdownFilter: dashboardBreakdown, source: 'dashboard' as const }
          : null

    return { propertyGroups, overriddenByTile, breakdown }
}

interface DateRangeSource {
    date_from?: string | null
    date_to?: string | null
}

export interface EffectiveDateOverride {
    source: OverrideSource
    dateFrom: string | null | undefined
    dateTo: string | null | undefined
    // The lower-priority layer this replaced, shown struck-through so the precedence is visible.
    replaced?: {
        source: OverrideSource | 'insight'
        dateFrom: string | null | undefined
        dateTo: string | null | undefined
    }
}

function hasDateBound(source: DateRangeSource | null | undefined): boolean {
    // `!= null` (not truthiness) matches the backend's `is not None`, so an explicit empty-string bound counts.
    return source?.date_from != null || source?.date_to != null
}

// Works out which layer's date range applies and what it replaced (tile beats dashboard beats the
// insight's own range); returns null when the insight's own range wins.
export function getDateRangeOverrideDisplay(
    insightDateRange: DateRangeSource | undefined,
    filterOverrideContext: InsightFilterOverrideContext | null | undefined,
    filtersOverride: DashboardFilter | undefined,
    tileFiltersOverride: TileFilters | null | undefined
): EffectiveDateOverride | null {
    const dashboardFilters = filterOverrideContext ? filterOverrideContext.dashboard : filtersOverride
    const tileFilters = filterOverrideContext ? filterOverrideContext.tile : tileFiltersOverride
    let winner: {
        source: OverrideSource
        dateFrom: string | null | undefined
        dateTo: string | null | undefined
    } | null = null
    if (hasDateBound(tileFilters)) {
        winner = { source: 'tile', dateFrom: tileFilters?.date_from, dateTo: tileFilters?.date_to }
    } else if (hasDateBound(dashboardFilters)) {
        winner = { source: 'dashboard', dateFrom: dashboardFilters?.date_from, dateTo: dashboardFilters?.date_to }
    }
    if (!winner) {
        return null
    }

    let replaced: EffectiveDateOverride['replaced']
    if (hasDateBound(filterOverrideContext?.overridden_dashboard)) {
        replaced = {
            source: 'dashboard',
            dateFrom: filterOverrideContext?.overridden_dashboard?.date_from,
            dateTo: filterOverrideContext?.overridden_dashboard?.date_to,
        }
    } else if (winner.source === 'tile' && hasDateBound(filtersOverride)) {
        replaced = { source: 'dashboard', dateFrom: filtersOverride?.date_from, dateTo: filtersOverride?.date_to }
    } else if (hasDateBound(insightDateRange)) {
        replaced = { source: 'insight', dateFrom: insightDateRange?.date_from, dateTo: insightDateRange?.date_to }
    }
    if (replaced && replaced.dateFrom === winner.dateFrom && replaced.dateTo === winner.dateTo) {
        replaced = undefined
    }

    return { ...winner, replaced }
}

// A scalar and its single-element array form mean the same filter, and the value list is a set, so
// compare as a sorted set.
function normalizeFilterValue(value: unknown): string {
    const entries = value == null ? [] : Array.isArray(value) ? value : [value]
    return JSON.stringify([...new Set(entries.map((entry) => JSON.stringify(entry)))].sort())
}

// The override round-trips through the backend and picks up normalized fields the raw override lacks, so a
// deep-equal fails — compare on the fields that actually identify a filter.
function isSamePropertyFilter(a: AnyPropertyFilter, b: AnyPropertyFilter): boolean {
    const operatorOf = (f: AnyPropertyFilter): string | undefined => ('operator' in f ? f.operator : undefined)
    return (
        (a.type ?? 'event') === (b.type ?? 'event') &&
        a.key === b.key &&
        (operatorOf(a) ?? 'exact') === (operatorOf(b) ?? 'exact') &&
        normalizeFilterValue(a.value) === normalizeFilterValue(b.value)
    )
}

function samePropertyFilters(a: AnyPropertyFilter[], b: AnyPropertyFilter[]): boolean {
    return a.length === b.length && a.every((f, i) => isSamePropertyFilter(f, b[i]))
}

// The shape `convertPropertiesToPropertyGroup` accepts: a group, a flat list, or nothing.
export type PropertiesInput = PropertyGroupFilter | AnyPropertyFilter[] | null | undefined

// Drop base leaves that are exact duplicates of a filter shown in a higher-priority override layer, so a
// filter the insight and an override both set shows once, on the layer that took priority. A shared key
// with a different value is left alone, since both genuinely AND together.
export function dropDuplicatesOfOverrides(
    base: PropertiesInput,
    overrideProperties: AnyPropertyFilter[]
): PropertiesInput {
    if (!base || overrideProperties.length === 0) {
        return base
    }
    const isDuplicate = (leaf: AnyPropertyFilter): boolean =>
        overrideProperties.some((override) => isSamePropertyFilter(leaf, override))
    if (Array.isArray(base)) {
        return base.filter((leaf) => !isDuplicate(leaf))
    }
    const values = (base.values ?? [])
        .map((subgroup) =>
            'values' in subgroup && Array.isArray(subgroup.values)
                ? { ...subgroup, values: (subgroup.values as AnyPropertyFilter[]).filter((leaf) => !isDuplicate(leaf)) }
                : subgroup
        )
        .filter((subgroup) => !('values' in subgroup && Array.isArray(subgroup.values) && subgroup.values.length === 0))
    return { ...base, values }
}

// The query returned for a dashboard tile already has the override's properties ANDed in as the trailing
// subgroup/tail, so pull that part out to attribute it rather than list it twice.
export function splitOutOverrideProperties(
    properties: PropertiesInput,
    overrideProperties: AnyPropertyFilter[]
): { base: PropertiesInput; overrideFound: boolean } {
    if (!properties || overrideProperties.length === 0) {
        return { base: properties, overrideFound: false }
    }
    // Flat list: the backend concatenated the override onto the end.
    if (Array.isArray(properties)) {
        const tailStart = properties.length - overrideProperties.length
        if (tailStart >= 0 && samePropertyFilters(properties.slice(tailStart), overrideProperties)) {
            return { base: properties.slice(0, tailStart), overrideFound: true }
        }
        return { base: properties, overrideFound: false }
    }
    // Group: the backend AND-wrapped the insight's group with the override as the final subgroup.
    const subgroups = properties.values ?? []
    const last = subgroups[subgroups.length - 1]
    if (last && samePropertyFilters(last.values as AnyPropertyFilter[], overrideProperties)) {
        return { base: { ...properties, values: subgroups.slice(0, -1) }, overrideFound: true }
    }
    return { base: properties, overrideFound: false }
}
