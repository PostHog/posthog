import { actions, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { InsightLogicProps, TrendsFilterType } from '~/types'
import { insightVizDataLogic } from '../insightVizDataLogic'
import { keyForInsightLogicProps } from '../sharedUtils'

import type { percentStackViewLogicType } from './percentStackViewLogicType'

export const percentStackViewLogic = kea<percentStackViewLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'EditorFilters', 'percentStackViewLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [insightVizDataLogic(props), ['isTrends', 'isStickiness', 'isLifecycle', 'insightFilter']],
        actions: [insightVizDataLogic(props), ['updateInsightFilter']],
    })),

    actions({
        setShowPercentStackView: (checked: boolean) => ({ checked }),
    }),

    selectors({
        showPercentStackView: [
            (s) => [s.isTrends, s.isStickiness, s.isLifecycle, s.insightFilter],
            (isTrends, isStickiness, isLifecycle, insightFilter) => {
                return !!(
                    (isTrends || isStickiness || isLifecycle) &&
                    (insightFilter as TrendsFilterType)?.show_percent_stack_view
                )
            },
        ],
    }),

    listeners(({ actions }) => ({
        setShowPercentStackView: ({ checked }) => {
            actions.updateInsightFilter({ show_percent_stack_view: checked })
        },
    })),
])
