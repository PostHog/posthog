import { DataColorToken, dataColorVars } from 'lib/colors'
import { getFunnelDatasetKey, getTrendDatasetKey, sortCohorts } from 'scenes/insights/utils'

import { isFunnelsQuery, isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { CohortType, DashboardTile, FunnelVizType, QueryBasedInsightModel } from '~/types'

import { BreakdownColorConfig } from './DashboardInsightColorsModal'

export type BreakdownValueAndType = Omit<BreakdownColorConfig, 'colorToken'>

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
                    const breakdownValues: BreakdownValueAndType[] = [
                        {
                            breakdownValue: 'Baseline',
                            breakdownType,
                        },
                    ]
                    tile.insight?.result?.forEach((result: any) => {
                        const key = getFunnelDatasetKey(result)
                        const keyParts = JSON.parse(key)
                        const breakdownValue = keyParts['breakdown_value']
                        breakdownValues.push({
                            breakdownValue: Array.isArray(breakdownValue) ? breakdownValue.join('::') : breakdownValue,
                            breakdownType,
                        })
                    })
                    return breakdownValues
                } else if (isTrendsQuery(querySource)) {
                    const breakdownType = querySource.breakdownFilter?.breakdown_type || 'event'
                    return tile.insight?.result?.map((result: any) => {
                        const key = getTrendDatasetKey(result)
                        const keyParts = JSON.parse(key)
                        const breakdownValue = keyParts['breakdown_value']
                        return {
                            breakdownValue: Array.isArray(breakdownValue) ? breakdownValue.join('::') : breakdownValue,
                            breakdownType,
                        }
                    })
                }
                return []
            }
            return []
        })
        .filter((value) => value != null)
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

/**
 * FNV-1a 32-bit hash. Deterministic, good distribution for short strings.
 * Used to pick a stable palette slot for a breakdown value so the same value
 * gets the same color across charts on a dashboard.
 */
function fnv1aHash(input: string): number {
    let hash = 0x811c9dc5
    for (let i = 0; i < input.length; i++) {
        hash ^= input.charCodeAt(i)
        hash = Math.imul(hash, 0x01000193)
    }
    return hash >>> 0
}

/**
 * Assign palette slots to breakdown values via hash with collision-avoidance.
 *
 * - Hash maps each value to a preferred palette slot.
 * - On collision, walks forward to the next free slot (modular).
 * - When the palette is exhausted, allows re-use (still deterministic in input order).
 *
 * Inputs are expected to be deterministically sorted (extractBreakdownValues already is)
 * so assignments don't shift when new values are appended lexically-later.
 */
export function autoAssignBreakdownColors(
    values: BreakdownValueAndType[],
    paletteSize: number = dataColorVars.length
): BreakdownColorConfig[] {
    const used = new Set<number>()
    const out: BreakdownColorConfig[] = []

    for (const v of values) {
        if (v.breakdownValue == null) {
            continue
        }
        const key = String(v.breakdownValue)
        const preferred = fnv1aHash(key) % paletteSize
        let slot = preferred
        for (let probe = 0; probe < paletteSize && used.has(slot); probe++) {
            slot = (slot + 1) % paletteSize
        }
        used.add(slot)
        out.push({
            breakdownValue: v.breakdownValue,
            breakdownType: v.breakdownType,
            colorToken: `preset-${slot + 1}` as DataColorToken,
        })
    }
    return out
}
