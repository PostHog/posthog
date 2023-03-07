import { kea, props, key, path, connect, selectors } from 'kea'
import { InsightLogicProps, TrendAPIResponse, TrendResult } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

import type { trendsDataLogicType } from './trendsDataLogicType'

export const trendsDataLogic = kea<trendsDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('all_trends')),
    path((key) => ['scenes', 'trends', 'trendsDataLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [insightDataLogic(props), ['insightData']],
    })),

    selectors({
        results: [
            (s) => [s.insightData],
            (insightData: TrendAPIResponse | null): TrendResult[] => {
                // TODO: after hooking up data manager, check that we have a trends result here
                if (insightData?.result && Array.isArray(insightData.result)) {
                    return insightData.result
                } else {
                    return []
                }
            },
        ],

        // indexedResults: [
        //     (s) => [s.filters, s.results, s.toggledLifecycles],
        //     (filters, _results, toggledLifecycles): IndexedTrendResult[] => {
        //         let results = _results || []
        //         results = results.map((result, index) => ({ ...result, seriesIndex: index }))
        //         // if (
        //         //     isFilterWithDisplay(filters) &&
        //         //     (filters.display === ChartDisplayType.ActionsBarValue ||
        //         //         filters.display === ChartDisplayType.ActionsPie)
        //         // ) {
        //         //     results.sort((a, b) => b.aggregated_value - a.aggregated_value)
        //         // } else if (isLifecycleFilter(filters)) {
        //         //     results = results.filter((result) => toggledLifecycles.includes(String(result.status)))
        //         // }
        //         return results.map((result, index) => ({ ...result, id: index } as IndexedTrendResult))
        //     },
        // ],
    }),
])
