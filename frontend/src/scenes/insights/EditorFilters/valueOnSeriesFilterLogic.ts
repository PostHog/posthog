import { actions, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { ChartDisplayType, InsightLogicProps, TrendsFilterType } from '~/types'
import { insightVizLogic } from '../insightVizLogic'
import { keyForInsightLogicProps } from '../sharedUtils'

import type { valueOnSeriesFilterLogicType } from './valueOnSeriesFilterLogicType'

export const valueOnSeriesFilterLogic = kea<valueOnSeriesFilterLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'EditorFilters', 'valueOnSeriesFilterLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [insightVizLogic(props), ['isTrends', 'isStickiness', 'isLifecycle', 'insightFilter']],
        actions: [insightVizLogic(props), ['updateInsightFilter']],
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
