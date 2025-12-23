import { TooltipItem } from 'lib/Chart'
import { AnomalyInfo, SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import { GraphDataset } from '~/types'

export interface AnomalyPointData {
    index: number
    date: string | null // Date/timestamp string for matching with chart labels
    score: number | null
    alertName: string
    seriesIndex: number
}

export function createTooltipData(
    tooltipDataPoints: TooltipItem<any>[],
    filterFn?: (s: SeriesDatum) => boolean,
    anomalyPoints?: AnomalyPointData[],
    chartDays?: string[] // The days/dates array from the chart dataset for date-based matching
): SeriesDatum[] {
    if (!tooltipDataPoints) {
        return []
    }

    const getAnomalyInfo = (dataIndex: number, datasetIndex: number): AnomalyInfo | undefined => {
        if (!anomalyPoints || anomalyPoints.length === 0) {
            return undefined
        }

        // Get the chart date at this index for date-based matching
        const chartDate = chartDays?.[dataIndex]

        // Try to match by date first (preferred), then fall back to index
        const anomaly = anomalyPoints.find((ap) => {
            if (ap.seriesIndex !== datasetIndex) {
                return false
            }
            // If we have both dates, match by date (handles different date ranges)
            if (chartDate && ap.date) {
                return chartDate === ap.date
            }
            // Fall back to index-based matching
            return ap.index === dataIndex
        })

        if (anomaly) {
            return {
                score: anomaly.score,
                alertName: anomaly.alertName,
            }
        }
        return undefined
    }

    let data = tooltipDataPoints
        .map((dp, idx) => {
            const pointDataset = (dp?.dataset ?? {}) as GraphDataset
            return {
                id: idx,
                dataIndex: dp.dataIndex,
                datasetIndex: dp.datasetIndex,
                seriesIndex: dp.dataIndex,
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
                hideTooltip: (pointDataset as any).hideTooltip,
                anomalyInfo: getAnomalyInfo(dp.dataIndex, dp.datasetIndex),
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
