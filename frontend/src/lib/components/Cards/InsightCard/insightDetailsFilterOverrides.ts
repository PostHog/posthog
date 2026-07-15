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
    // Dashboard property filters the tile contradicts — they don't apply, but we surface them
    // struck-through so the precedence is visible rather than silently dropped.
    overriddenByTile: AnyPropertyFilter[]
    breakdown: { breakdownFilter: NonNullable<DashboardFilter['breakdown_filter']>; source: OverrideSource } | null
}

// Property filters stack (AND-combine) by default; a tile filter only replaces the dashboard's when the
// two provably contradict. Mirrors backend `filters_contradict` in dashboard_filter_conflicts.py — keep
// the two in step.
const POSITIVE_EXACT_OPERATORS = new Set(['exact', 'in'])
const NEGATIVE_EXACT_OPERATORS = new Set(['is_not', 'not_in'])
// Operators that can never match an unset value; only these conflict with is_not_set.
const MATCHES_ONLY_SET_VALUES = new Set(['exact', 'in', 'icontains', 'regex', 'is_set'])
const INCOMPARABLE_FILTER_TYPES = new Set(['cohort', 'hogql'])

function canonicalizeValue(value: unknown): string {
    if (typeof value === 'boolean') {
        return value ? 'true' : 'false'
    }
    return String(value)
}

function normalizedValues(value: unknown): string[] | null {
    if (value == null) {
        return null
    }
    const values = Array.isArray(value) ? value : [value]
    return values.length === 0 ? null : values.map(canonicalizeValue)
}

function operatorAndValues(filter: AnyPropertyFilter): [string, string[] | null] {
    const operator = ('operator' in filter && filter.operator) || 'exact'
    return [operator, normalizedValues('value' in filter ? filter.value : undefined)]
}

function sameProperty(a: AnyPropertyFilter, b: AnyPropertyFilter): boolean {
    for (const f of [a, b]) {
        if (f.key == null || INCOMPARABLE_FILTER_TYPES.has((f.type as string) ?? '')) {
            return false
        }
    }
    const groupTypeIndex = (f: AnyPropertyFilter): unknown => ('group_type_index' in f ? f.group_type_index : undefined)
    return a.key === b.key && a.type === b.type && groupTypeIndex(a) === groupTypeIndex(b)
}

function contradictsOneWay(opA: string, valuesA: string[] | null, opB: string, valuesB: string[] | null): boolean {
    if (opB === 'is_not_set' && MATCHES_ONLY_SET_VALUES.has(opA)) {
        return opA === 'is_set' || valuesA !== null
    }
    if (valuesA === null || valuesB === null) {
        return false
    }
    const setA = new Set(valuesA)
    const setB = new Set(valuesB)
    if (POSITIVE_EXACT_OPERATORS.has(opA)) {
        if (NEGATIVE_EXACT_OPERATORS.has(opB)) {
            return [...setA].every((v) => setB.has(v))
        }
        if (POSITIVE_EXACT_OPERATORS.has(opB)) {
            return ![...setA].some((v) => setB.has(v))
        }
    }
    if (opA === 'icontains' && opB === 'not_icontains') {
        const positive = valuesA.map((v) => v.toLowerCase())
        const negative = valuesB.map((v) => v.toLowerCase())
        return positive.every((p) => negative.some((n) => p.includes(n)))
    }
    if (opA === 'regex' && opB === 'not_regex') {
        return valuesA.length === 1 && valuesB.length === 1 && valuesA[0] === valuesB[0]
    }
    return false
}

// Whether two filters on the same property provably contradict, so ANDing them could never match.
function filtersContradict(a: AnyPropertyFilter, b: AnyPropertyFilter): boolean {
    if (!sameProperty(a, b)) {
        return false
    }
    const [opA, valuesA] = operatorAndValues(a)
    const [opB, valuesB] = operatorAndValues(b)
    return contradictsOneWay(opA, valuesA, opB, valuesB) || contradictsOneWay(opB, valuesB, opA, valuesA)
}

export function getEffectiveFilterOverrides(
    filtersOverride: DashboardFilter | undefined,
    tileFiltersOverride: TileFilters | null | undefined
): EffectiveFilterOverrides {
    const tileProperties = tileFiltersOverride?.properties ?? []
    const dashboardProperties: AnyPropertyFilter[] = []
    const overriddenByTile: AnyPropertyFilter[] = []
    for (const property of filtersOverride?.properties ?? []) {
        if (tileProperties.some((tile) => filtersContradict(property, tile))) {
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
