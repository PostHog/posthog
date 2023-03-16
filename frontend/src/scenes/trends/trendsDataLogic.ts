import { kea, props, key, path, connect, selectors } from 'kea'
import { ChartDisplayType, InsightLogicProps, LifecycleToggle, TrendAPIResponse, TrendResult } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

import type { trendsDataLogicType } from './trendsDataLogicType'
import { IndexedTrendResult } from './types'

export const trendsDataLogic = kea<trendsDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('all_trends')),
    path((key) => ['scenes', 'trends', 'trendsDataLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [insightDataLogic(props), ['insightData', 'display', 'lifecycleFilter']],
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

        indexedResults: [
            (s) => [s.results, s.display, s.lifecycleFilter],
            (results, display, lifecycleFilter): IndexedTrendResult[] => {
                let indexedResults = results.map((result, index) => ({ ...result, seriesIndex: index }))
                if (
                    display &&
                    (display === ChartDisplayType.ActionsBarValue || display === ChartDisplayType.ActionsPie)
                ) {
                    indexedResults.sort((a, b) => b.aggregated_value - a.aggregated_value)
                } else if (lifecycleFilter && lifecycleFilter.toggledLifecycles) {
                    indexedResults = indexedResults.filter((result) =>
                        // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
                        lifecycleFilter.toggledLifecycles!.includes(String(result.status) as LifecycleToggle)
                    )
                }
                return indexedResults.map((result, index) => ({ ...result, id: index }))
            },
        ],
    }),
])
