import { connect, kea, key, path, props, selectors } from 'kea'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { BoxPlotDatum } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { keyForInsightLogicProps } from '../../sharedUtils'
import type { boxPlotChartLogicType } from './boxPlotChartLogicType'

export const boxPlotChartLogic = kea<boxPlotChartLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'BoxPlot', 'boxPlotChartLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [insightVizDataLogic(props), ['insightData']],
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
    }),
])
