import { actions, connect, kea, key, listeners, path, props } from 'kea'
import { InsightLogicProps } from '~/types'
import { insightVizDataLogic } from '../insightVizDataLogic'
import { keyForInsightLogicProps } from '../sharedUtils'

import type { percentStackViewLogicType } from './percentStackViewLogicType'

export const percentStackViewLogic = kea<percentStackViewLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'EditorFilters', 'percentStackViewLogic', key]),

    connect((props: InsightLogicProps) => ({
        actions: [insightVizDataLogic(props), ['updateInsightFilter']],
    })),

    actions({
        setShowPercentStackView: (checked: boolean) => ({ checked }),
    }),

    listeners(({ actions }) => ({
        setShowPercentStackView: ({ checked }) => {
            actions.updateInsightFilter({ show_percent_stack_view: checked })
        },
    })),
])
