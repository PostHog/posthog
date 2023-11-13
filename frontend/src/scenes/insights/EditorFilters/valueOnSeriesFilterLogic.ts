import { actions, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { ChartDisplayType, InsightLogicProps, TrendsFilterType } from '~/types'
import { insightVizDataLogic } from '../insightVizDataLogic'
import { keyForInsightLogicProps } from '../sharedUtils'

import type { valueOnSeriesFilterLogicType } from './valueOnSeriesFilterLogicType'

export const valueOnSeriesFilterLogic = kea<valueOnSeriesFilterLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'EditorFilters', 'valueOnSeriesFilterLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [insightVizDataLogic(props), ['isTrends', 'isStickiness', 'isLifecycle', 'insightFilter']],
        actions: [insightVizDataLogic(props), ['updateInsightFilter']],
    })),

    actions({
        setValueOnSeries: (checked: boolean) => ({ checked }),
    }),

    selectors({
        valueOnSeries: [
            (s) => [s.isTrends, s.isStickiness, s.isLifecycle, s.insightFilter],
            (isTrends, isStickiness, isLifecycle, insightFilter) => {
                return !!(
                    ((isTrends || isStickiness || isLifecycle) &&
                        (insightFilter as TrendsFilterType)?.show_values_on_series) ||
                    // pie charts have value checked by default
                    (isTrends &&
                        (insightFilter as TrendsFilterType)?.display === ChartDisplayType.ActionsPie &&
                        (insightFilter as TrendsFilterType)?.show_values_on_series === undefined)
                )
            },
        ],
    }),

    listeners(({ actions }) => ({
        setValueOnSeries: ({ checked }) => {
            actions.updateInsightFilter({ show_values_on_series: checked })
        },
    })),
])
