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

export const boxPlotChartLogic = kea<boxPlotChartLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'BoxPlot', 'boxPlotChartLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [insightVizDataLogic(props), ['insightData', 'yAxisScaleType', 'querySource', 'interval']],
    })),
    selectors({
        boxplotData: [
            (s) => [s.insightData],
            (insightData): BoxPlotDatum[] => {
                if (!insightData?.boxplot_data) {
                    return []
                }
                return insightData.boxplot_data
            },
        ],
        labels: [
            (s) => [s.boxplotData],
            (boxplotData: BoxPlotDatum[]): string[] => {
                return boxplotData.map((d) => d.label)
            },
        ],
        chartData: [
            (s) => [s.boxplotData],
            (boxplotData: BoxPlotDatum[]): BoxPlotChartDatum[] => {
                return boxplotData.map((d) => ({
                    min: d.min,
                    q1: d.p25,
                    median: d.median,
                    q3: d.p75,
                    max: d.max,
                    mean: d.mean,
                    whiskerMin: d.min,
                    whiskerMax: d.max,
                }))
            },
        ],
    }),
])
