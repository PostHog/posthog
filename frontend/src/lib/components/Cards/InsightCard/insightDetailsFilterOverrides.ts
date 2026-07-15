import { DashboardFilter, TileFilters } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, PropertyGroupFilter } from '~/types'

// Pure precedence logic for the dashboard/tile filter overrides shown in the insight detail popup. It
// re-derives the merge the backend already computes (`merge_filters_by_priority` in
// apply_dashboard_filters.py) purely to attribute each shown filter to its source ("Dashboard"/"Tile").
// Keep the tie-break here in step with that backend rule.

export type OverrideSource = 'dashboard' | 'tile'

export interface EffectiveFilterOverrides {
    // Non-overlapping keys from both layers contribute; dashboard first to match backend order.
    propertyGroups: { properties: AnyPropertyFilter[]; source: OverrideSource }[]
    // Dashboard property filters the tile shadows on the same key — they don't apply, but we surface them
    // struck-through so the precedence is visible rather than silently dropped.
    overriddenByTile: AnyPropertyFilter[]
    breakdown: { breakdownFilter: NonNullable<DashboardFilter['breakdown_filter']>; source: OverrideSource } | null
}

// Deterministic stringify with sorted object keys, matching the backend's `json.dumps(key, sort_keys=True)`
// so an object-valued property key is compared by value rather than collapsing to "[object Object]".
function stableStringify(value: unknown): string {
    if (Array.isArray(value)) {
        return `[${value.map(stableStringify).join(',')}]`
    }
    if (value && typeof value === 'object') {
        return `{${Object.entries(value as Record<string, unknown>)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([key, nested]) => `${JSON.stringify(key)}:${stableStringify(nested)}`)
            .join(',')}}`
    }
    return JSON.stringify(value)
}

// The (type, group_type_index, key) a property filter targets — the unit at which a tile takes precedence.
// Mirrors backend `_property_identity`; group_type_index is included so a tile override on one group type
// doesn't shadow the same key on a different group type.
function propertyIdentity(property: AnyPropertyFilter): string {
    const type = 'type' in property ? property.type : 'event'
    const groupTypeIndex = 'group_type_index' in property ? property.group_type_index : undefined
    const rawKey = 'key' in property ? property.key : ''
    const key = rawKey && typeof rawKey === 'object' ? stableStringify(rawKey) : String(rawKey)
    return `${type}::${groupTypeIndex ?? ''}::${key}`
}

// Property filters merge per key: a tile filter replaces the dashboard's on the same key.
export function getEffectiveFilterOverrides(
    filtersOverride: DashboardFilter | undefined,
    tileFiltersOverride: TileFilters | null | undefined
): EffectiveFilterOverrides {
    const tileProperties = tileFiltersOverride?.properties ?? []
    const tileKeys = new Set(tileProperties.map(propertyIdentity))
    const dashboardProperties: AnyPropertyFilter[] = []
    const overriddenByTile: AnyPropertyFilter[] = []
    for (const property of filtersOverride?.properties ?? []) {
        if (tileKeys.has(propertyIdentity(property))) {
            overriddenByTile.push(property)
        } else {
            dashboardProperties.push(property)
        }
    }
    const propertyGroups: EffectiveFilterOverrides['propertyGroups'] = []
    if (dashboardProperties.length > 0) {
        propertyGroups.push({ properties: dashboardProperties, source: 'dashboard' })
    }
    if (tileProperties.length > 0) {
        propertyGroups.push({ properties: tileProperties, source: 'tile' })
    }

    const breakdown = tileFiltersOverride?.breakdown_filter
        ? { breakdownFilter: tileFiltersOverride.breakdown_filter, source: 'tile' as const }
        : filtersOverride?.breakdown_filter
          ? { breakdownFilter: filtersOverride.breakdown_filter, source: 'dashboard' as const }
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
    filtersOverride: DashboardFilter | undefined,
    tileFiltersOverride: TileFilters | null | undefined
): EffectiveDateOverride | null {
    let winner: {
        source: OverrideSource
        dateFrom: string | null | undefined
        dateTo: string | null | undefined
    } | null = null
    if (hasDateBound(tileFiltersOverride)) {
        winner = { source: 'tile', dateFrom: tileFiltersOverride?.date_from, dateTo: tileFiltersOverride?.date_to }
    } else if (hasDateBound(filtersOverride)) {
        winner = { source: 'dashboard', dateFrom: filtersOverride?.date_from, dateTo: filtersOverride?.date_to }
    }
    if (!winner) {
        return null
    }

    let replaced: EffectiveDateOverride['replaced']
    if (winner.source === 'tile' && hasDateBound(filtersOverride)) {
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
