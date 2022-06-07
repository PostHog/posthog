import { kea } from 'kea'
import { TooltipItem } from 'chart.js'
import { GraphDataset } from '~/types'
import { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { lineGraphLogicType } from './lineGraphLogicType'

// TODO: Eventually we should move all state from LineGraph into this logic
export const lineGraphLogic = kea<lineGraphLogicType>({
    path: ['scenes', 'insights', 'LineGraph', 'lineGraphLogic'],
    selectors: {
        createTooltipData: [
            () => [],
            () =>
                (tooltipDataPoints: TooltipItem<any>[], filterFn: (s: SeriesDatum) => boolean): SeriesDatum[] => {
                    return tooltipDataPoints
                        ?.map((dp, idx) => {
                            const pointDataset = (dp?.dataset ?? {}) as GraphDataset
                            return {
                                id: idx,
                                dataIndex: dp.dataIndex,
                                datasetIndex: dp.datasetIndex,
                                dotted: !!pointDataset?.dotted,
                                breakdown_value:
                                    pointDataset?.breakdown_value ??
                                    pointDataset?.breakdownValues?.[dp.dataIndex] ??
                                    undefined,
                                compare_label:
                                    pointDataset?.compare_label ??
                                    pointDataset?.compareLabels?.[dp.dataIndex] ??
                                    undefined,
                                action: pointDataset?.action ?? pointDataset?.actions?.[dp.dataIndex] ?? undefined,
                                label: pointDataset?.label ?? undefined,
                                color: Array.isArray(pointDataset.backgroundColor)
                                    ? pointDataset.backgroundColor?.[dp.dataIndex]
                                    : pointDataset.backgroundColor,
                                count: pointDataset?.data?.[dp.dataIndex] || 0,
                                filter: pointDataset?.filter ?? {},
                                reached_from_step_count: pointDataset?.reached_from_step_count?.[dp.dataIndex],
                                reached_to_step_count: pointDataset?.reached_to_step_count?.[dp.dataIndex],
                            }
                        })
                        ?.sort((a, b) => {
                            // Sort by descending order and fallback on alphabetic sort
                            return (
                                b.count - a.count ||
                                (a.label === undefined || b.label === undefined ? -1 : a.label.localeCompare(b.label))
                            )
                        })
                        ?.filter(filterFn)
                        ?.map((s, id) => ({
                            ...s,
                            id,
                        }))
                },
        ],
    },
})
