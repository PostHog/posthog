import { TooltipItem } from 'lib/Chart'
import { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import { GraphDataset } from '~/types'

export function createTooltipData(
    tooltipDataPoints: TooltipItem<any>[],
    filterFn?: (s: SeriesDatum) => boolean
): SeriesDatum[] {
    if (!tooltipDataPoints) {
        return []
    }
    let data = tooltipDataPoints
        .map((dp, idx) => {
            const pointDataset = (dp?.dataset ?? {}) as GraphDataset
            return {
                id: idx,
                dataIndex: dp.dataIndex,
                datasetIndex: dp.datasetIndex,
                dotted: !!pointDataset?.dotted,
                breakdown_value:
                    pointDataset?.breakdown_value ??
                    pointDataset?.breakdownLabels?.[dp.dataIndex] ??
                    pointDataset?.breakdownValues?.[dp.dataIndex] ??
                    undefined,
                compare_label: pointDataset?.compare_label ?? pointDataset?.compareLabels?.[dp.dataIndex] ?? undefined,
                action: pointDataset?.action ?? pointDataset?.actions?.[dp.dataIndex] ?? undefined,
                label: pointDataset?.label ?? pointDataset.labels?.[dp.dataIndex] ?? undefined,
                order: pointDataset?.order ?? 0,
                color: Array.isArray(pointDataset.borderColor)
                    ? pointDataset.borderColor?.[dp.dataIndex]
                    : pointDataset.borderColor,
                count: pointDataset?.data?.[dp.dataIndex] || 0,
                filter: pointDataset?.filter ?? {},
            }
        })
        .sort((a, b) => {
            // Sort by descending order and fallback on alphabetic sort
            return (
                b.count - a.count ||
                (a.label === undefined || b.label === undefined ? -1 : a.label.localeCompare(b.label))
            )
        })
    if (filterFn) {
        data = data.filter(filterFn)
    }
    return data.map((s, id) => ({
        ...s,
        id,
    }))
}
