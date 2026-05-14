import { connect, kea, key, path, props, selectors } from 'kea'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { BoxPlotDatum } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { keyForInsightLogicProps } from '../../sharedUtils'
import type { boxPlotChartLogicType } from './boxPlotChartLogicType'

export interface BoxPlotChartDatum {
    min: number
    q1: number
    median: number
    q3: number
    max: number
    mean: number
    whiskerMin: number
    whiskerMax: number
}

export interface BoxPlotSeriesData {
    seriesIndex: number
    seriesLabel: string
    data: BoxPlotChartDatum[]
    rawData: BoxPlotDatum[]
}

export const boxPlotChartLogic = kea<boxPlotChartLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'BoxPlot', 'boxPlotChartLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            ['insightData', 'yAxisScaleType', 'querySource', 'interval', 'trendsFilter'],
        ],
    })),
    selectors({
        boxplotData: [
            (s) => [s.insightData],
            (insightData): BoxPlotDatum[] => {
                const result = insightData?.result ?? insightData?.results
                // TODO: remove boxplot_data fallback once cached responses have rotated (added 2026-04-16)
                const data = Array.isArray(result) && result.length > 0 ? result : insightData?.boxplot_data
                if (!Array.isArray(data) || data.length === 0) {
                    return []
                }
                return data
            },
        ],
        seriesGroups: [
            (s) => [s.boxplotData, s.trendsFilter],
            (boxplotData: BoxPlotDatum[], trendsFilter): BoxPlotSeriesData[] => {
                const excludeOutliers = trendsFilter?.excludeBoxPlotOutliers !== false
                const groupMap = new Map<number, { label: string; data: BoxPlotDatum[] }>()

                for (const d of boxplotData) {
                    const idx = d.series_index ?? 0
                    const label = d.series_label ?? 'Distribution'
                    if (!groupMap.has(idx)) {
                        groupMap.set(idx, { label, data: [] })
                    }
                    groupMap.get(idx)!.data.push(d)
                }

                return Array.from(groupMap.entries())
                    .sort(([a], [b]) => a - b)
                    .map(([seriesIndex, group]) => ({
                        seriesIndex,
                        seriesLabel: group.label,
                        rawData: group.data,
                        data: group.data.map((d) => {
                            const iqr = d.p75 - d.p25
                            return {
                                min: d.min,
                                q1: d.p25,
                                median: d.median,
                                q3: d.p75,
                                max: d.max,
                                mean: d.mean,
                                whiskerMin: excludeOutliers ? Math.max(d.min, d.p25 - 1.5 * iqr) : d.min,
                                whiskerMax: excludeOutliers ? Math.min(d.max, d.p75 + 1.5 * iqr) : d.max,
                            }
                        }),
                    }))
            },
        ],
        dateLabels: [
            (s) => [s.seriesGroups],
            (seriesGroups: BoxPlotSeriesData[]): string[] => {
                if (seriesGroups.length === 0) {
                    return []
                }
                return seriesGroups[0].rawData.map((d) => d.label)
            },
        ],
    }),
])
