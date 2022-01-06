import { kea } from 'kea'
import { TooltipItem } from 'chart.js'
import { GraphDataset } from '~/types'
import { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { lineGraphLogicType } from './lineGraphLogicType'

export const lineGraphLogic = kea<lineGraphLogicType>({
    path: ['scenes', 'insights', 'LineGraph', 'lineGraphLogic'],
    selectors: {
        createTooltipData: [
            () => [],
            () =>
                (tooltipDataPoints: TooltipItem<any>[], filterFn: (s: SeriesDatum) => boolean): SeriesDatum[] => {
                    console.log('DATAPOINTS,', tooltipDataPoints)
                    return tooltipDataPoints
                        ?.map((dp, idx) => {
                            const pointDataset = (dp?.dataset ?? {}) as GraphDataset
                            console.log('POINT DATASET', pointDataset)
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
                            }
                        })
                        ?.sort((a, b) => {
                            if (a.action?.order === undefined || b.action?.order === undefined) {
                                return -1
                            }
                            return a.action.order - b.action.order
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
