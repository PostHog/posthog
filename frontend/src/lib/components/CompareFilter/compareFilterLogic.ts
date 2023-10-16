import { kea } from 'kea'
import { ChartDisplayType, InsightLogicProps } from '~/types'
import type { compareFilterLogicType } from './compareFilterLogicType'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizLogic } from 'scenes/insights/insightVizLogic'

export const compareFilterLogic = kea<compareFilterLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['lib', 'components', 'CompareFilter', 'compareFilterLogic', key],
    connect: (props: InsightLogicProps) => ({
        values: [
            insightLogic(props),
            ['canEditInsight'],
            insightVizLogic(props),
            ['compare', 'display', 'insightFilter', 'isLifecycle', 'dateRange'],
        ],
        actions: [insightVizLogic(props), ['updateInsightFilter']],
    }),

    actions: () => ({
        setCompare: (compare: boolean) => ({ compare }),
        toggleCompare: true,
    }),

    selectors: {
        disabled: [
            (s) => [s.canEditInsight, s.isLifecycle, s.display, s.dateRange],
            (canEditInsight, isLifecycle, display, dateRange) =>
                !canEditInsight ||
                isLifecycle ||
                display === ChartDisplayType.WorldMap ||
                dateRange?.date_from === 'all',
        ],
    },

    listeners: ({ values, actions }) => ({
        setCompare: ({ compare }) => {
            actions.updateInsightFilter({ compare })
        },
        toggleCompare: () => {
            actions.setCompare(!values.compare)
        },
    }),
})
