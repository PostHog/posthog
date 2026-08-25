import { DataColorToken, dataColorVars } from 'lib/colors'
import { getFunnelDatasetKey, getTrendDatasetKey, isNullBreakdown, isOtherBreakdown } from 'scenes/insights/utils'

import { BreakdownFilter } from '~/queries/schema/schema-general'
import { hasBreakdownFilter, isFunnelsQuery, isInsightVizNode, isRetentionQuery, isTrendsQuery } from '~/queries/utils'
import { DashboardTile, FunnelVizType, QueryBasedInsightModel } from '~/types'

export type BreakdownColorSource = 'auto' | 'manual'

export type BreakdownColorConfig = {
    colorToken: DataColorToken | null
    breakdownValue: string
    breakdownType: BreakdownFilter['breakdown_type']
    /** Normalized breakdown property the value belongs to (see getBreakdownPropertyKey).
     * Scopes the color to tiles breaking down by that property. Entries without one predate
     * property scoping and match their value under any property. */
    breakdownProperty?: string
    /** Entries without a source predate auto-assignment and are treated as manual pins. */
    source?: BreakdownColorSource
}

export type BreakdownValueAndType = Pick<BreakdownColorConfig, 'breakdownValue' | 'breakdownType' | 'breakdownProperty'>

/** Label of the synthetic baseline row funnel insights contribute to the colors table. */
export const FUNNEL_BASELINE_BREAKDOWN_LABEL = 'Baseline'

/** Joins the parts of a multi-breakdown value in normalized form. A control character scalar
 * values can't realistically contain, so an array like ["a", "b"] never collides with a scalar
 * value like "a::b" (the display separator, which does occur in real property values). */
export const MULTI_BREAKDOWN_SEPARATOR = '\u001f'

/** Property key of every cohort breakdown. Cohort ids identify globally rather than per
 * property, so all cohort breakdowns form one color group, matching their pre-scoping
 * behavior of one identity per cohort id. */
export const COHORT_BREAKDOWN_PROPERTY_KEY = 'cohort'

/** Breakdown values arrive as string | number | boolean | array depending on insight type and
 * persistence round-trips, while configs compare with strict equality. One canonical string form
 * keeps a value matching its config across tiles, insight types, and saves. */
export function normalizeBreakdownValue(value: unknown): string | null {
    if (value == null) {
        return null
    }
    return Array.isArray(value) ? value.join(MULTI_BREAKDOWN_SEPARATOR) : String(value)
}

/** Restores the array form of a normalized multi-breakdown value so labels format each part. */
export function denormalizeBreakdownValue(value: string): string | string[] {
    return value.includes(MULTI_BREAKDOWN_SEPARATOR) ? value.split(MULTI_BREAKDOWN_SEPARATOR) : value
}

// The group type index only means something for group breakdowns; other types can carry a
// stale one, which must not split a property into two groups.
function breakdownPropertyPart(
    type: string,
    groupTypeIndex: number | null | undefined,
    property: string | number
): string {
    return `${type}:${type === 'group' ? (groupTypeIndex ?? '') : ''}:${property}`
}

/** Normalized identity of what a query breaks down by: type, group index, and property of
 * each part, multi parts joined in order. A single breakdown and a one-entry multi breakdown
 * of the same property produce the same key, so their values share colors. Display options
 * (URL normalization, histogram bins, limits) stay out of the key because they change how
 * values render, not which property they come from. Returns null without a breakdown. */
export function getBreakdownPropertyKey(breakdownFilter: BreakdownFilter | null | undefined): string | null {
    if (breakdownFilter?.breakdowns?.length) {
        return breakdownFilter.breakdowns
            .map((breakdown) =>
                breakdownPropertyPart(breakdown.type ?? 'event', breakdown.group_type_index, breakdown.property)
            )
            .join(MULTI_BREAKDOWN_SEPARATOR)
    }
    if (breakdownFilter?.breakdown == null) {
        return null
    }
    const breakdownType = breakdownFilter.breakdown_type ?? 'event'
    if (breakdownType === 'cohort') {
        return COHORT_BREAKDOWN_PROPERTY_KEY
    }
    return breakdownPropertyPart(
        breakdownType,
        breakdownFilter.breakdown_group_type_index,
        Array.isArray(breakdownFilter.breakdown)
            ? breakdownFilter.breakdown.join(MULTI_BREAKDOWN_SEPARATOR)
            : breakdownFilter.breakdown
    )
}

export type BreakdownPropertyKeyPart = {
    type: BreakdownFilter['breakdown_type']
    property: string
}

/** Type and property name of a key's parts, for display. Not meaningful for the cohort key. */
export function parseBreakdownPropertyKey(key: string): BreakdownPropertyKeyPart[] {
    // The first two colon-separated fields are type and group index; the property itself may
    // contain colons, so everything past the second one belongs to it.
    return key.split(MULTI_BREAKDOWN_SEPARATOR).map((part) => {
        const fields = part.split(':')
        return { type: fields[0] as BreakdownFilter['breakdown_type'], property: fields.slice(2).join(':') }
    })
}

export function breakdownConfigMatches(
    config: BreakdownValueAndType,
    breakdownValue: unknown,
    breakdownType: BreakdownFilter['breakdown_type'] | null | undefined,
    breakdownPropertyKey?: string | null
): boolean {
    const normalized = normalizeBreakdownValue(breakdownValue)
    if (normalized == null || normalizeBreakdownValue(config.breakdownValue) !== normalized) {
        return false
    }
    // A property key already encodes each part's type, so scoped entries match on it alone;
    // property-less entries keep the legacy value-and-type match under any property.
    return config.breakdownProperty != null
        ? config.breakdownProperty === breakdownPropertyKey
        : config.breakdownType === (breakdownType ?? 'event')
}

/** True when two configs denote the same entry: same normalized value, type, and property
 * scope. Unlike breakdownConfigMatches, a property-less entry only equals another
 * property-less one, so scoped and legacy entries for one value can coexist. */
export function breakdownConfigIdentityMatches(a: BreakdownValueAndType, b: BreakdownValueAndType): boolean {
    return (
        normalizeBreakdownValue(a.breakdownValue) === normalizeBreakdownValue(b.breakdownValue) &&
        (a.breakdownType ?? 'event') === (b.breakdownType ?? 'event') &&
        (a.breakdownProperty ?? null) === (b.breakdownProperty ?? null)
    )
}

export function findBreakdownColorConfig(
    configs: BreakdownColorConfig[] | undefined | null,
    breakdownValue: unknown,
    breakdownType: BreakdownFilter['breakdown_type'] | null | undefined,
    breakdownPropertyKey?: string | null
): BreakdownColorConfig | undefined {
    if (normalizeBreakdownValue(breakdownValue) == null) {
        return undefined
    }
    // A property-scoped entry beats a property-less one, which acts as a fallback pin
    // across all properties.
    const scoped =
        breakdownPropertyKey != null
            ? configs?.find(
                  (config) =>
                      config.breakdownProperty != null &&
                      breakdownConfigMatches(config, breakdownValue, breakdownType, breakdownPropertyKey)
              )
            : undefined
    return (
        scoped ??
        configs?.find(
            (config) =>
                config.breakdownProperty == null &&
                breakdownConfigMatches(config, breakdownValue, breakdownType, breakdownPropertyKey)
        )
    )
}

/** Merge configs by (breakdownValue, breakdownType, breakdownProperty), earlier lists winning
 * over later ones. Scoped and property-less entries for the same value stay separate, so a
 * scoped pin can shadow a legacy one per property without erasing it elsewhere. Values are
 * normalized on the way out, migrating legacy non-string entries on the next save. */
export function mergeBreakdownColorConfigs(...configLists: BreakdownColorConfig[][]): BreakdownColorConfig[] {
    const merged: BreakdownColorConfig[] = []
    for (const configs of configLists) {
        for (const config of configs) {
            const breakdownValue = normalizeBreakdownValue(config.breakdownValue)
            if (breakdownValue == null) {
                continue
            }
            if (!merged.some((c) => breakdownConfigIdentityMatches(c, config))) {
                merged.push({ ...config, breakdownValue })
            }
        }
    }
    return merged
}

// Time-to-convert renders a single-color histogram, so it has nothing to contribute.
function funnelVizRendersBreakdownSeries(funnelVizType: FunnelVizType | undefined): boolean {
    return (
        funnelVizType === undefined || funnelVizType === FunnelVizType.Steps || funnelVizType === FunnelVizType.Trends
    )
}

function makeBreakdownValue(
    breakdownValue: string,
    breakdownType: BreakdownFilter['breakdown_type'],
    breakdownPropertyKey: string | null
): BreakdownValueAndType {
    return breakdownPropertyKey == null
        ? { breakdownValue, breakdownType }
        : { breakdownValue, breakdownType, breakdownProperty: breakdownPropertyKey }
}

function extractTileBreakdownValues(tile: DashboardTile<QueryBasedInsightModel>): BreakdownValueAndType[] {
    if (!isInsightVizNode(tile.insight?.query)) {
        return []
    }

    const querySource = tile.insight?.query.source
    let breakdownValues: (BreakdownValueAndType | null)[] = []
    if (isFunnelsQuery(querySource)) {
        const funnelVizType = querySource.funnelsFilter?.funnelVizType
        if (!funnelVizRendersBreakdownSeries(funnelVizType)) {
            return []
        }
        const isStepsViz = funnelVizType === undefined || funnelVizType === FunnelVizType.Steps
        const breakdownType = querySource.breakdownFilter?.breakdown_type || 'event'
        const propertyKey = getBreakdownPropertyKey(querySource.breakdownFilter)
        // Only the steps visualization renders a baseline series. The baseline is a funnel
        // sentinel rather than a value of the breakdown property, so it stays property-less
        // and one pin covers it on every funnel tile.
        breakdownValues = isStepsViz
            ? [
                  {
                      breakdownValue: FUNNEL_BASELINE_BREAKDOWN_LABEL,
                      breakdownType,
                  },
              ]
            : []
        tile.insight?.result?.forEach((result: any) => {
            const key = getFunnelDatasetKey(result)
            const breakdownValue = normalizeBreakdownValue(JSON.parse(key)['breakdown_value'])
            breakdownValues.push(
                breakdownValue == null ? null : makeBreakdownValue(breakdownValue, breakdownType, propertyKey)
            )
        })
    } else if (isTrendsQuery(querySource)) {
        const breakdownType = querySource.breakdownFilter?.breakdown_type || 'event'
        const propertyKey = getBreakdownPropertyKey(querySource.breakdownFilter)
        breakdownValues =
            tile.insight?.result?.map((result: any): BreakdownValueAndType | null => {
                const key = getTrendDatasetKey(result)
                const breakdownValue = normalizeBreakdownValue(JSON.parse(key)['breakdown_value'])
                return breakdownValue == null ? null : makeBreakdownValue(breakdownValue, breakdownType, propertyKey)
            }) || []
    } else if (isRetentionQuery(querySource) && hasBreakdownFilter(querySource.breakdownFilter)) {
        const breakdownType = querySource.breakdownFilter.breakdown_type || 'event'
        const propertyKey = getBreakdownPropertyKey(querySource.breakdownFilter)
        // Retention results carry breakdown_value directly. There is no dataset-key helper
        // like trends/funnels have, because retention has no resultCustomizations whose
        // persisted keys the extraction would need to stay in sync with.
        breakdownValues =
            tile.insight?.result?.map((result: any): BreakdownValueAndType | null => {
                const breakdownValue = normalizeBreakdownValue(result.breakdown_value)
                return breakdownValue == null ? null : makeBreakdownValue(breakdownValue, breakdownType, propertyKey)
            }) || []
    }

    return breakdownValues
        .filter((value): value is BreakdownValueAndType => value != null)
        .reduce<BreakdownValueAndType[]>((acc, curr) => {
            if (!acc.some((x) => x.breakdownValue === curr.breakdownValue && x.breakdownType === curr.breakdownType)) {
                acc.push(curr)
            }
            return acc
        }, [])
}

/** Breakdown values per tile, deduplicated within each tile; tiles without values are dropped.
 * Tile identity matters for assignment: which values co-occur on one chart decides which
 * colors may collide, and how many tiles share a value decides whether it gets one at all. */
export function extractBreakdownValuesByTile(
    insightTiles: DashboardTile<QueryBasedInsightModel>[] | null
): BreakdownValueAndType[][] {
    if (insightTiles == null) {
        return []
    }
    return insightTiles.map(extractTileBreakdownValues).filter((values) => values.length > 0)
}

/** True when any tile's query would contribute breakdown values once loaded, but its results are
 * unavailable (a refresh errored or was aborted before the insight ever got results). Such a
 * tile's breakdown values are unknown rather than absent, so tile counts under-report sharing:
 * pruning or persisting auto colors in this state would drop entries that are still valid. */
export function hasUnresolvedBreakdownTiles(insightTiles: DashboardTile<QueryBasedInsightModel>[] | null): boolean {
    return (insightTiles ?? []).some((tile) => {
        if (tile.insight?.result != null || !isInsightVizNode(tile.insight?.query)) {
            return false
        }
        const querySource = tile.insight?.query.source
        if (isFunnelsQuery(querySource)) {
            return (
                funnelVizRendersBreakdownSeries(querySource.funnelsFilter?.funnelVizType) &&
                hasBreakdownFilter(querySource.breakdownFilter)
            )
        }
        if (isTrendsQuery(querySource) || isRetentionQuery(querySource)) {
            return hasBreakdownFilter(querySource.breakdownFilter)
        }
        return false
    })
}

/** Deduplicated breakdown values across all tiles, clustered by breakdown property in the
 * order properties first appear on the dashboard, then ordered within each property the way
 * auto-assignment ranks them, so the colors modal lists values the way colors are handed out. */
export function extractBreakdownValues(
    insightTiles: DashboardTile<QueryBasedInsightModel>[] | null
): BreakdownValueAndType[] {
    const tileBreakdownValues = extractBreakdownValuesByTile(insightTiles)
    const stats = collectValueTileStats(tileBreakdownValues)
    const compareAssignmentRank = buildAssignmentRankComparator(stats)
    const propertyOrder = new Map<string | null, number>()
    stats.tileProperties.forEach((property, tileIndex) => {
        if (!propertyOrder.has(property)) {
            propertyOrder.set(property, tileIndex)
        }
    })
    return tileBreakdownValues
        .flat()
        .reduce<BreakdownValueAndType[]>((acc, curr) => {
            if (!acc.some((x) => breakdownConfigIdentityMatches(x, curr))) {
                acc.push(curr)
            }
            return acc
        }, [])
        .sort(
            (a, b) =>
                // Property-less rows (like the funnel baseline) sort ahead of the clusters.
                (propertyOrder.get(a.breakdownProperty ?? null) ?? -1) -
                    (propertyOrder.get(b.breakdownProperty ?? null) ?? -1) || compareAssignmentRank(a, b)
        )
}

export type BreakdownValueGroup = { breakdownProperty?: string; values: BreakdownValueAndType[] }

/** Cluster an extractBreakdownValues list into per-property groups, keeping the list's order
 * within and across groups. The property-less group (the funnel baseline, legacy values)
 * moves to the end: its entries span every property, so it reads as an appendix to the
 * property sections rather than the first one. */
export function groupBreakdownValuesByProperty(values: BreakdownValueAndType[]): BreakdownValueGroup[] {
    const grouped = new Map<string | null, BreakdownValueAndType[]>()
    for (const value of values) {
        const key = value.breakdownProperty ?? null
        const group = grouped.get(key)
        if (group) {
            group.push(value)
        } else {
            grouped.set(key, [value])
        }
    }
    const groups = [...grouped.entries()].map(
        ([breakdownProperty, groupValues]): BreakdownValueGroup =>
            breakdownProperty == null ? { values: groupValues } : { breakdownProperty, values: groupValues }
    )
    return [...groups.filter((g) => g.breakdownProperty != null), ...groups.filter((g) => g.breakdownProperty == null)]
}

/** Sentinel rows keep their built-in muted/fixed treatment instead of an assigned palette color. */
export function isAutoAssignableBreakdownValue(breakdownValue: string): boolean {
    return (
        breakdownValue !== FUNNEL_BASELINE_BREAKDOWN_LABEL &&
        !isOtherBreakdown(breakdownValue) &&
        !isNullBreakdown(breakdownValue)
    )
}

const PRESET_TOKEN_REGEX = /^preset-(\d+)$/

function presetTokenToSlot(colorToken: DataColorToken | null | undefined, paletteSize: number): number | null {
    const match = colorToken?.match(PRESET_TOKEN_REGEX)
    return match ? (Number(match[1]) - 1) % paletteSize : null
}

function slotToPresetToken(slot: number): DataColorToken {
    return `preset-${slot + 1}` as DataColorToken
}

// code-unit comparison, not localeCompare — assignment order must not depend on the client locale
function compareAssignmentOrder(a: BreakdownValueAndType, b: BreakdownValueAndType): number {
    const propertyA = a.breakdownProperty ?? ''
    const propertyB = b.breakdownProperty ?? ''
    return (
        (a.breakdownType ?? 'event').localeCompare(b.breakdownType ?? 'event') ||
        (propertyA < propertyB ? -1 : propertyA > propertyB ? 1 : 0) ||
        (a.breakdownValue < b.breakdownValue ? -1 : a.breakdownValue > b.breakdownValue ? 1 : 0)
    )
}

// NUL separators keep the fields from colliding: normalized values can't contain NUL, and
// property keys join their parts with \u001f.
function breakdownIdentityKey(value: BreakdownValueAndType): string {
    return `${value.breakdownProperty ?? ''}\u0000${value.breakdownType ?? 'event'}\u0000${value.breakdownValue}`
}

function breakdownValueKey(value: BreakdownValueAndType): string {
    return `${value.breakdownType ?? 'event'}\u0000${value.breakdownValue}`
}

type TileStats = { tiles: number[]; positionSum: number }

type ValueTileStats = {
    /** Keyed by property, type, and value: the unit colors are assigned to. */
    byIdentity: Map<string, TileStats & { value: BreakdownValueAndType }>
    /** Keyed by type and value across all properties. Decides sharing and rank for every
     * value, so a value re-used under different properties counts as re-used, and covers
     * property-less legacy configs, which match their value wherever it appears. */
    byValue: Map<string, TileStats>
    /** Property key of each tile, for per-property slot bookkeeping. */
    tileProperties: (string | null)[]
}

function collectValueTileStats(tileBreakdownValues: BreakdownValueAndType[][]): ValueTileStats {
    const byIdentity: ValueTileStats['byIdentity'] = new Map()
    const byValue: ValueTileStats['byValue'] = new Map()
    const tileProperties: (string | null)[] = []
    tileBreakdownValues.forEach((values, tileIndex) => {
        // All real values of a tile share the tile's breakdown property; only sentinel rows
        // (the funnel baseline) are property-less.
        tileProperties.push(values.find((value) => value.breakdownProperty != null)?.breakdownProperty ?? null)
        values.forEach((value, position) => {
            const identityEntry = byIdentity.get(breakdownIdentityKey(value))
            if (identityEntry) {
                identityEntry.tiles.push(tileIndex)
                identityEntry.positionSum += position
            } else {
                byIdentity.set(breakdownIdentityKey(value), { value, tiles: [tileIndex], positionSum: position })
            }
            const valueEntry = byValue.get(breakdownValueKey(value))
            if (valueEntry) {
                valueEntry.tiles.push(tileIndex)
                valueEntry.positionSum += position
            } else {
                byValue.set(breakdownValueKey(value), { tiles: [tileIndex], positionSum: position })
            }
        })
    })
    return { byIdentity, byValue, tileProperties }
}

// Which tiles an entry shows on, for collision checks: the tiles of its own scope. A scoped
// entry only colors its property's tiles, while a property-less one colors the value everywhere.
function statsOf(stats: ValueTileStats, value: BreakdownValueAndType): TileStats | undefined {
    return value.breakdownProperty != null
        ? stats.byIdentity.get(breakdownIdentityKey(value))
        : stats.byValue.get(breakdownValueKey(value))
}

// How often a value is re-used, counted across every property it appears under. Sharing and
// rank read this rather than the per-property count, so a value carried by several properties
// is treated as one re-used value.
function valueStatsOf(stats: ValueTileStats, value: BreakdownValueAndType): TileStats | undefined {
    return stats.byValue.get(breakdownValueKey(value))
}

// Rank by re-use first, so the values shared by the most charts claim the earliest
// slots. Ties break by the values' ranking within their own charts: each tile's value
// list is in chart series order, and positions are summed across a value's tiles,
// which compares like the average because tile counts are equal whenever the sum is
// reached. Plain value order settles full ties (e.g. values leading disjoint tiles).
// Both terms count the value across properties, so its entries rank next to each other
// and the first one assigned sets the color the others copy.
function buildAssignmentRankComparator(
    stats: ValueTileStats
): (a: BreakdownValueAndType, b: BreakdownValueAndType) => number {
    return (a, b) => {
        const entryA = valueStatsOf(stats, a)
        const entryB = valueStatsOf(stats, b)
        return (
            (entryB?.tiles.length ?? 0) - (entryA?.tiles.length ?? 0) ||
            (entryA?.positionSum ?? 0) - (entryB?.positionSum ?? 0) ||
            compareAssignmentOrder(a, b)
        )
    }
}

/** Membership test for values that appear on two or more tiles, counted across every property
 * they appear under. Only those receive a dashboard-wide auto color: cross-tile consistency is
 * what the feature buys, and a value on a single insight has nothing to stay consistent with.
 * The count ignores which property carried the value, so one tile of each of two properties is
 * enough, those being the values whose color would otherwise be settled per property.
 *
 * An entry also has to still show somewhere in its own scope, so pruning drops an entry scoped
 * to a property the dashboard no longer breaks down by, even while the value lives on
 * elsewhere. */
export function buildSharedBreakdownValueLookup(
    tileBreakdownValues: BreakdownValueAndType[][]
): (value: BreakdownValueAndType) => boolean {
    const stats = collectValueTileStats(tileBreakdownValues)
    return (value) =>
        (statsOf(stats, value)?.tiles.length ?? 0) >= 1 && (valueStatsOf(stats, value)?.tiles.length ?? 0) >= 2
}

/** Complete existing configs with palette slots for breakdown values shared by 2+ tiles.
 *
 * Each property is its own color world: slot exclusivity is tracked per property, so a
 * dashboard breaking down by several properties reuses the palette from the first slot for
 * each of them, the way standalone insights do, instead of exhausting it across the union of
 * all values. Unrelated values under different properties may therefore share a color; they
 * never meet on one tile, since a tile breaks down by exactly one property.
 *
 * A value carried by several properties is one value to a reader, so its entries aim for one
 * color: whichever is assigned first sets the slot, and the rest copy it unless that slot is
 * taken within their own property. Ranking counts a value's tiles across properties, so those
 * entries sort next to each other and copy before other values claim slots. Copying can still
 * fail, which is visible as one value in two colors and is the honest outcome: within a
 * property, two values sharing a color on one chart would be worse. Property-less legacy
 * entries keep matching their value everywhere and claim their slot in every property they
 * appear under.
 *
 * Stability comes from persistence, not from the algorithm: manual pins never move, and
 * persisted auto entries keep their slots unless two of them meet on one tile with the same
 * slot (a new tile landed, or the entry predates collision-aware assignment); of such a
 * pair, the lower-ranked entry moves. Uncovered shared values and displaced entries are
 * ranked by how many charts re-use them, most first. Re-use ties break by the values'
 * ranking within their own charts, then by a locale-independent value order. Each value
 * takes the lowest slot unused within its property while slots last, then a slot its own
 * tiles don't show yet, then the slot least used on those tiles: a duplicate color on two
 * different charts is invisible, on one chart it isn't.
 *
 * Returns the full config list: existing entries in their original order (re-slotted ones
 * replaced in place, so an unchanged dashboard round-trips deep-equal for the save diff),
 * with new assignments appended.
 */
export function applyAutoBreakdownColors(
    tileBreakdownValues: BreakdownValueAndType[][],
    existingConfigs: BreakdownColorConfig[],
    paletteSize: number = dataColorVars.length
): BreakdownColorConfig[] {
    if (paletteSize <= 0) {
        return [...existingConfigs]
    }

    const stats = collectValueTileStats(tileBreakdownValues)
    const tilesOf = (value: BreakdownValueAndType): number[] => statsOf(stats, value)?.tiles ?? []
    const compareAssignmentRank = buildAssignmentRankComparator(stats)

    // Per-tile slot usage drives collision checks; per-property usage keeps distinct values
    // of one property on distinct colors while slots last.
    const tileSlotCounts: Map<number, number>[] = tileBreakdownValues.map(() => new Map())
    const usedByProperty = new Map<string | null, Set<number>>()
    const markUsed = (property: string | null, slot: number): void => {
        let used = usedByProperty.get(property)
        if (!used) {
            used = new Set()
            usedByProperty.set(property, used)
        }
        used.add(slot)
    }
    // The slot each value settled on, so its entries under other properties can copy it. First
    // claim wins, and pins claim before auto entries, so a pinned color is the one copied.
    const slotByValue = new Map<string, number>()
    const claimSlot = (slot: number, value: BreakdownValueAndType, tiles: number[]): void => {
        // Claiming for the entry's own property even without visible tiles keeps a
        // temporarily hidden value's slot reserved within its property.
        markUsed(value.breakdownProperty ?? null, slot)
        if (!slotByValue.has(breakdownValueKey(value))) {
            slotByValue.set(breakdownValueKey(value), slot)
        }
        for (const tile of tiles) {
            markUsed(stats.tileProperties[tile] ?? null, slot)
            tileSlotCounts[tile].set(slot, (tileSlotCounts[tile].get(slot) ?? 0) + 1)
        }
    }
    // The slots an entry must treat as taken: its own property's plus, for property-less
    // entries spanning several properties, those of every property its tiles belong to.
    const usedFor = (value: BreakdownValueAndType): Set<number> => {
        const used = new Set(usedByProperty.get(value.breakdownProperty ?? null) ?? [])
        for (const tile of tilesOf(value)) {
            usedByProperty.get(stats.tileProperties[tile] ?? null)?.forEach((slot) => used.add(slot))
        }
        return used
    }

    // Manual pins are user intent and never move; they claim their slots first.
    const autoConfigs: BreakdownColorConfig[] = []
    for (const config of existingConfigs) {
        const slot = presetTokenToSlot(config.colorToken, paletteSize)
        if (slot == null) {
            continue
        }
        if (config.source === 'auto') {
            autoConfigs.push(config)
        } else {
            claimSlot(slot, config, tilesOf(config))
        }
    }

    // Walking persisted auto entries in rank order means that of a colliding pair, the
    // lower-ranked value (re-used by fewer charts, or trailing in chart order) moves.
    const displaced: BreakdownValueAndType[] = []
    for (const config of [...autoConfigs].sort(compareAssignmentRank)) {
        const slot = presetTokenToSlot(config.colorToken, paletteSize)!
        const tiles = tilesOf(config)
        const collidesWithinTile = tiles.some((tile) => (tileSlotCounts[tile].get(slot) ?? 0) > 0)
        if (collidesWithinTile) {
            displaced.push(
                makeBreakdownValue(config.breakdownValue, config.breakdownType, config.breakdownProperty ?? null)
            )
        } else {
            claimSlot(slot, config, tiles)
        }
    }

    const uncovered = [...stats.byIdentity.values()]
        .map(({ value }) => value)
        .filter((value) => (valueStatsOf(stats, value)?.tiles.length ?? 0) >= 2)
        .filter(
            (value) =>
                isAutoAssignableBreakdownValue(value.breakdownValue) &&
                !findBreakdownColorConfig(
                    existingConfigs,
                    value.breakdownValue,
                    value.breakdownType,
                    value.breakdownProperty
                )?.colorToken
        )

    const allSlots = Array.from({ length: paletteSize }, (_, slot) => slot)
    const assignments = new Map<string, BreakdownColorConfig>()
    for (const candidate of [...uncovered, ...displaced].sort(compareAssignmentRank)) {
        const tiles = tilesOf(candidate)
        const used = usedFor(candidate)
        const usedOnOwnTiles = (slot: number): number =>
            tiles.reduce((sum, tile) => sum + (tileSlotCounts[tile].get(slot) ?? 0), 0)
        // The slot this value took under another property comes first, even when a lower one is
        // free: one color per value reads better than the palette's earliest colors.
        const sharedSlot = slotByValue.get(breakdownValueKey(candidate))
        const slot =
            (sharedSlot != null && !used.has(sharedSlot) ? sharedSlot : undefined) ??
            allSlots.find((slot) => !used.has(slot)) ??
            allSlots.find((slot) => usedOnOwnTiles(slot) === 0) ??
            allSlots.reduce((best, slot) => (usedOnOwnTiles(slot) < usedOnOwnTiles(best) ? slot : best))
        claimSlot(slot, candidate, tiles)
        assignments.set(breakdownIdentityKey(candidate), {
            ...makeBreakdownValue(
                candidate.breakdownValue,
                candidate.breakdownType,
                candidate.breakdownProperty ?? null
            ),
            colorToken: slotToPresetToken(slot),
            source: 'auto',
        })
    }

    const result = existingConfigs.map((config) => {
        const replacement = assignments.get(breakdownIdentityKey(config))
        if (replacement) {
            assignments.delete(breakdownIdentityKey(config))
            return replacement
        }
        return config
    })
    return [...result, ...assignments.values()]
}

/** One series of a tile, as input to position-based fallback completion. */
export type TileFallbackSeries = {
    /** Palette position of the series; current/previous compare pairs share one position. */
    position: number
    /** Token the series resolves to via a value override (dashboard breakdown color or
     * explicit insight result customization), or null when it falls back to its position. */
    overrideToken: DataColorToken | null
}

/** Position-based fallback tokens for the series of one tile that have no value override.
 *
 * Without dashboard colors, series get `preset-(position + 1)`: consecutive palette slots,
 * which are designed to look distinct next to each other. Value overrides break that
 * sequence, since they occupy slots scattered across the whole dashboard, so a
 * position-colored neighbor can land on the same slot as an override on the same chart.
 * Instead, non-overridden series fill the slots the tile's overrides do not use, in
 * position order, cycling through those free slots once they run out (a duplicate among
 * far-apart positions beats duplicating an override's color).
 *
 * Returns an empty map when the tile has no overrides, so override-free tiles keep plain
 * position colors and render exactly as a standalone insight, and when overrides cover the
 * whole palette, where no free slot exists to complete with.
 */
export function computeTileFallbackTokens(
    series: TileFallbackSeries[],
    paletteSize: number
): Map<number, DataColorToken> {
    const fallbackTokens = new Map<number, DataColorToken>()
    if (paletteSize <= 0) {
        return fallbackTokens
    }

    const overriddenPositions = new Set<number>()
    const usedSlots = new Set<number>()
    for (const { position, overrideToken } of series) {
        const slot = presetTokenToSlot(overrideToken, paletteSize)
        if (slot != null) {
            overriddenPositions.add(position)
            usedSlots.add(slot)
        }
    }
    if (usedSlots.size === 0 || usedSlots.size >= paletteSize) {
        return fallbackTokens
    }

    const freeSlots = Array.from({ length: paletteSize }, (_, slot) => slot).filter((slot) => !usedSlots.has(slot))
    const positions = [...new Set(series.map((s) => s.position))]
        .filter((position) => !overriddenPositions.has(position))
        .sort((a, b) => a - b)
    positions.forEach((position, index) => {
        fallbackTokens.set(position, slotToPresetToken(freeSlots[index % freeSlots.length]))
    })
    return fallbackTokens
}
