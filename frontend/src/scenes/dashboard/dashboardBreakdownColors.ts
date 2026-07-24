import { DataColorToken, dataColorVars } from 'lib/colors'
import {
    getFunnelDatasetKey,
    getTrendDatasetKey,
    isNullBreakdown,
    isOtherBreakdown,
    sortCohorts,
} from 'scenes/insights/utils'

import { BreakdownFilter } from '~/queries/schema/schema-general'
import { isFunnelsQuery, isInsightVizNode, isTrendsQuery } from '~/queries/utils'
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

export function extractBreakdownValues(
    insightTiles: DashboardTile<QueryBasedInsightModel>[] | null,
    cohorts: CohortType[] | null
): BreakdownValueAndType[] {
    if (insightTiles == null) {
        return []
    }

    return insightTiles
        .flatMap((tile) => {
            if (isInsightVizNode(tile.insight?.query)) {
                const querySource = tile.insight?.query.source
                if (
                    isFunnelsQuery(querySource) &&
                    (querySource.funnelsFilter?.funnelVizType === undefined ||
                        querySource.funnelsFilter?.funnelVizType === FunnelVizType.Steps)
                ) {
                    const breakdownType = querySource.breakdownFilter?.breakdown_type || 'event'
                    const breakdownValues: (BreakdownValueAndType | null)[] = [
                        {
                            breakdownValue: FUNNEL_BASELINE_BREAKDOWN_LABEL,
                            breakdownType,
                        },
                    ]
                    tile.insight?.result?.forEach((result: any) => {
                        const key = getFunnelDatasetKey(result)
                        const breakdownValue = normalizeBreakdownValue(JSON.parse(key)['breakdown_value'])
                        breakdownValues.push(breakdownValue == null ? null : { breakdownValue, breakdownType })
                    })
                    return breakdownValues
                } else if (isTrendsQuery(querySource)) {
                    const breakdownType = querySource.breakdownFilter?.breakdown_type || 'event'
                    return (
                        tile.insight?.result?.map((result: any): BreakdownValueAndType | null => {
                            const key = getTrendDatasetKey(result)
                            const breakdownValue = normalizeBreakdownValue(JSON.parse(key)['breakdown_value'])
                            return breakdownValue == null ? null : { breakdownValue, breakdownType }
                        }) || []
                    )
                }
                return []
            }
            return []
        })
        .filter((value): value is BreakdownValueAndType => value != null)
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

/** Assign palette slots to breakdown values that no existing config covers.
 *
 * Stability comes from persistence, not from the algorithm: existing configs (manual pins and
 * previously materialized auto entries) keep their slots untouched, and only uncovered values are
 * assigned here — sorted deterministically, filling free slots in ascending order. Once the
 * palette is exhausted further values wrap around it; getColorFromToken wraps the same way.
 */
export function computeAutoBreakdownColors(
    visibleValues: BreakdownValueAndType[],
    existingConfigs: BreakdownColorConfig[],
    paletteSize: number = dataColorVars.length
): BreakdownColorConfig[] {
    const usedSlots = new Set<number>()
    for (const config of existingConfigs) {
        const match = config.colorToken?.match(PRESET_TOKEN_REGEX)
        if (match) {
            usedSlots.add((Number(match[1]) - 1) % paletteSize)
        }
    }

    const candidates = visibleValues
        .filter(
            (value) =>
                isAutoAssignableBreakdownValue(value.breakdownValue) &&
                !findBreakdownColorConfig(existingConfigs, value.breakdownValue, value.breakdownType)?.colorToken
        )
        // code-unit comparison, not localeCompare — assignment order must not depend on the client locale
        .sort(
            (a, b) =>
                (a.breakdownType ?? 'event').localeCompare(b.breakdownType ?? 'event') ||
                (a.breakdownValue < b.breakdownValue ? -1 : a.breakdownValue > b.breakdownValue ? 1 : 0)
        )

    const freeSlots = Array.from({ length: paletteSize }, (_, slot) => slot).filter((slot) => !usedSlots.has(slot))
    let wrapCursor = 0

    const assigned: BreakdownColorConfig[] = []
    for (const candidate of candidates) {
        if (assigned.some((c) => breakdownConfigMatches(c, candidate.breakdownValue, candidate.breakdownType))) {
            continue
        }
        const slot = freeSlots.length > 0 ? freeSlots.shift()! : wrapCursor++ % paletteSize
        assigned.push({
            breakdownValue: candidate.breakdownValue,
            breakdownType: candidate.breakdownType,
            colorToken: `preset-${slot + 1}` as DataColorToken,
            source: 'auto',
        })
    }
    return assigned
}
