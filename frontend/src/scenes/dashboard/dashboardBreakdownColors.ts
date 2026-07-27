import { DataColorToken, dataColorVars } from 'lib/colors'
import {
    getFunnelDatasetKey,
    getTrendDatasetKey,
    isNullBreakdown,
    isOtherBreakdown,
    sortCohorts,
} from 'scenes/insights/utils'

import { BreakdownFilter } from '~/queries/schema/schema-general'
import { hasBreakdownFilter, isFunnelsQuery, isInsightVizNode, isRetentionQuery, isTrendsQuery } from '~/queries/utils'
import { CohortType, DashboardTile, FunnelVizType, QueryBasedInsightModel } from '~/types'

export type BreakdownColorSource = 'auto' | 'manual'

export type BreakdownColorConfig = {
    colorToken: DataColorToken | null
    breakdownValue: string
    breakdownType: BreakdownFilter['breakdown_type']
    /** Entries without a source predate auto-assignment and are treated as manual pins. */
    source?: BreakdownColorSource
}

export type BreakdownValueAndType = Pick<BreakdownColorConfig, 'breakdownValue' | 'breakdownType'>

/** Label of the synthetic baseline row funnel insights contribute to the colors table. */
export const FUNNEL_BASELINE_BREAKDOWN_LABEL = 'Baseline'

/** Joins the parts of a multi-breakdown value in normalized form. A control character scalar
 * values can't realistically contain, so an array like ["a", "b"] never collides with a scalar
 * value like "a::b" (the display separator, which does occur in real property values). */
export const MULTI_BREAKDOWN_SEPARATOR = '\u001f'

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

export function breakdownConfigMatches(
    config: BreakdownValueAndType,
    breakdownValue: unknown,
    breakdownType: BreakdownFilter['breakdown_type'] | null | undefined
): boolean {
    const normalized = normalizeBreakdownValue(breakdownValue)
    return (
        normalized != null &&
        normalizeBreakdownValue(config.breakdownValue) === normalized &&
        config.breakdownType === (breakdownType ?? 'event')
    )
}

export function findBreakdownColorConfig(
    configs: BreakdownColorConfig[] | undefined | null,
    breakdownValue: unknown,
    breakdownType: BreakdownFilter['breakdown_type'] | null | undefined
): BreakdownColorConfig | undefined {
    if (normalizeBreakdownValue(breakdownValue) == null) {
        return undefined
    }
    return configs?.find((config) => breakdownConfigMatches(config, breakdownValue, breakdownType))
}

/** Merge configs by (breakdownValue, breakdownType), earlier lists winning over later ones.
 * Values are normalized on the way out, migrating legacy non-string entries on the next save. */
export function mergeBreakdownColorConfigs(...configLists: BreakdownColorConfig[][]): BreakdownColorConfig[] {
    const merged: BreakdownColorConfig[] = []
    for (const configs of configLists) {
        for (const config of configs) {
            const breakdownValue = normalizeBreakdownValue(config.breakdownValue)
            if (breakdownValue == null) {
                continue
            }
            if (!merged.some((c) => breakdownConfigMatches(c, breakdownValue, config.breakdownType))) {
                merged.push({ ...config, breakdownValue })
            }
        }
    }
    return merged
}

function extractTileBreakdownValues(tile: DashboardTile<QueryBasedInsightModel>): BreakdownValueAndType[] {
    if (!isInsightVizNode(tile.insight?.query)) {
        return []
    }

    const querySource = tile.insight?.query.source
    let breakdownValues: (BreakdownValueAndType | null)[] = []
    if (isFunnelsQuery(querySource)) {
        const funnelVizType = querySource.funnelsFilter?.funnelVizType
        const isStepsViz = funnelVizType === undefined || funnelVizType === FunnelVizType.Steps
        // Time-to-convert renders a single-color histogram, so it has nothing to contribute.
        if (!isStepsViz && funnelVizType !== FunnelVizType.Trends) {
            return []
        }
        const breakdownType = querySource.breakdownFilter?.breakdown_type || 'event'
        // Only the steps visualization renders a baseline series.
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
            breakdownValues.push(breakdownValue == null ? null : { breakdownValue, breakdownType })
        })
    } else if (isTrendsQuery(querySource)) {
        const breakdownType = querySource.breakdownFilter?.breakdown_type || 'event'
        breakdownValues =
            tile.insight?.result?.map((result: any): BreakdownValueAndType | null => {
                const key = getTrendDatasetKey(result)
                const breakdownValue = normalizeBreakdownValue(JSON.parse(key)['breakdown_value'])
                return breakdownValue == null ? null : { breakdownValue, breakdownType }
            }) || []
    } else if (isRetentionQuery(querySource) && hasBreakdownFilter(querySource.breakdownFilter)) {
        const breakdownType = querySource.breakdownFilter.breakdown_type || 'event'
        // Retention results carry breakdown_value directly. There is no dataset-key helper
        // like trends/funnels have, because retention has no resultCustomizations whose
        // persisted keys the extraction would need to stay in sync with.
        breakdownValues =
            tile.insight?.result?.map((result: any): BreakdownValueAndType | null => {
                const breakdownValue = normalizeBreakdownValue(result.breakdown_value)
                return breakdownValue == null ? null : { breakdownValue, breakdownType }
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

export function extractBreakdownValues(
    insightTiles: DashboardTile<QueryBasedInsightModel>[] | null,
    cohorts: CohortType[] | null
): BreakdownValueAndType[] {
    return extractBreakdownValuesByTile(insightTiles)
        .flat()
        .reduce<BreakdownValueAndType[]>((acc, curr) => {
            if (!acc.some((x) => x.breakdownValue === curr.breakdownValue && x.breakdownType === curr.breakdownType)) {
                acc.push(curr)
            }
            return acc
        }, [])
        .sort((a, b) => {
            if (a.breakdownType === 'cohort' && b.breakdownType === 'cohort') {
                return sortCohorts(a.breakdownValue, b.breakdownValue, cohorts)
            }

            // put cohorts at the end
            if (a.breakdownType === 'cohort' || b.breakdownType === 'cohort') {
                return a.breakdownType === 'cohort' ? 1 : -1
            }

            return String(a.breakdownValue).localeCompare(String(b.breakdownValue))
        })
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
    return (
        (a.breakdownType ?? 'event').localeCompare(b.breakdownType ?? 'event') ||
        (a.breakdownValue < b.breakdownValue ? -1 : a.breakdownValue > b.breakdownValue ? 1 : 0)
    )
}

// A NUL escape cannot appear in a normalized value (the multi-breakdown separator is
// \u001f), so value/type pairs cannot collide in this key space.
function breakdownValueTileKey(value: BreakdownValueAndType): string {
    return `${value.breakdownType ?? 'event'}\u0000${value.breakdownValue}`
}

/** Membership test for values that appear on two or more tiles. Only those receive a
 * dashboard-wide auto color: cross-tile consistency is what the feature buys, and a value
 * unique to one tile would burn a palette slot every other tile then has to avoid. */
export function buildSharedBreakdownValueLookup(
    tileBreakdownValues: BreakdownValueAndType[][]
): (value: BreakdownValueAndType) => boolean {
    const tileCounts = new Map<string, number>()
    for (const values of tileBreakdownValues) {
        for (const value of values) {
            const key = breakdownValueTileKey(value)
            tileCounts.set(key, (tileCounts.get(key) ?? 0) + 1)
        }
    }
    return (value) => (tileCounts.get(breakdownValueTileKey(value)) ?? 0) >= 2
}

/** Complete existing configs with palette slots for breakdown values shared by 2+ tiles.
 *
 * Stability comes from persistence, not from the algorithm: manual pins never move, and
 * persisted auto entries keep their slots unless two of them meet on one tile with the same
 * slot (a new tile landed, or the entry predates collision-aware assignment). Uncovered
 * shared values and collision-displaced auto entries are then assigned in deterministic
 * order: the lowest globally-unused slot while slots last, then a slot the value's own
 * tiles don't show yet, then the slot least used on those tiles. A duplicate color on two
 * different charts is invisible; on one chart it isn't, so exhaustion prefers cross-tile
 * reuse over within-tile reuse.
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

    const valueTiles = new Map<string, { value: BreakdownValueAndType; tiles: number[] }>()
    tileBreakdownValues.forEach((values, tileIndex) => {
        for (const value of values) {
            const key = breakdownValueTileKey(value)
            const entry = valueTiles.get(key)
            if (entry) {
                entry.tiles.push(tileIndex)
            } else {
                valueTiles.set(key, { value, tiles: [tileIndex] })
            }
        }
    })
    const tilesOf = (value: BreakdownValueAndType): number[] =>
        valueTiles.get(breakdownValueTileKey(value))?.tiles ?? []

    // Per-tile slot usage drives collision checks; global usage keeps distinct values on
    // distinct colors while free slots last.
    const tileSlotCounts: Map<number, number>[] = tileBreakdownValues.map(() => new Map())
    const globalUsed = new Set<number>()
    const claimSlot = (slot: number, tiles: number[]): void => {
        globalUsed.add(slot)
        for (const tile of tiles) {
            tileSlotCounts[tile].set(slot, (tileSlotCounts[tile].get(slot) ?? 0) + 1)
        }
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
            claimSlot(slot, tilesOf(config))
        }
    }

    // Walking persisted auto entries in assignment order means that of a colliding pair,
    // the later-sorted value is the one that moves.
    const displaced: BreakdownValueAndType[] = []
    for (const config of [...autoConfigs].sort(compareAssignmentOrder)) {
        const slot = presetTokenToSlot(config.colorToken, paletteSize)!
        const tiles = tilesOf(config)
        const collidesWithinTile = tiles.some((tile) => (tileSlotCounts[tile].get(slot) ?? 0) > 0)
        if (collidesWithinTile) {
            displaced.push({ breakdownValue: config.breakdownValue, breakdownType: config.breakdownType })
        } else {
            claimSlot(slot, tiles)
        }
    }

    const uncovered = [...valueTiles.values()]
        .filter(({ tiles }) => tiles.length >= 2)
        .map(({ value }) => value)
        .filter(
            (value) =>
                isAutoAssignableBreakdownValue(value.breakdownValue) &&
                !findBreakdownColorConfig(existingConfigs, value.breakdownValue, value.breakdownType)?.colorToken
        )

    const allSlots = Array.from({ length: paletteSize }, (_, slot) => slot)
    const assignments = new Map<string, BreakdownColorConfig>()
    for (const candidate of [...uncovered, ...displaced].sort(compareAssignmentOrder)) {
        const tiles = tilesOf(candidate)
        const usedOnOwnTiles = (slot: number): number =>
            tiles.reduce((sum, tile) => sum + (tileSlotCounts[tile].get(slot) ?? 0), 0)
        const slot =
            allSlots.find((slot) => !globalUsed.has(slot)) ??
            allSlots.find((slot) => usedOnOwnTiles(slot) === 0) ??
            allSlots.reduce((best, slot) => (usedOnOwnTiles(slot) < usedOnOwnTiles(best) ? slot : best))
        claimSlot(slot, tiles)
        assignments.set(breakdownValueTileKey(candidate), {
            breakdownValue: candidate.breakdownValue,
            breakdownType: candidate.breakdownType,
            colorToken: slotToPresetToken(slot),
            source: 'auto',
        })
    }

    const result = existingConfigs.map((config) => {
        const replacement = assignments.get(breakdownValueTileKey(config))
        if (replacement) {
            assignments.delete(breakdownValueTileKey(config))
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
