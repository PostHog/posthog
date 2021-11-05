import { kea } from 'kea'
import { InsightLogicProps, ViewType } from '~/types'
import { compareFilterLogicType } from './compareFilterLogicType'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightLogic } from 'scenes/insights/insightLogic'

export const compareFilterLogic = kea<compareFilterLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['lib', 'components', 'CompareFilter', 'compareFilterLogic', key],

    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters']],
        actions: [insightLogic(props), ['setFilters']],
    }),

    actions: () => ({
        setCompare: (compare: boolean) => ({ compare }),
        toggleCompare: true,
    }),

    selectors: {
        compare: [(s) => [s.filters], ({ compare }) => compare],
        disabled: [
            (s) => [s.filters],
            ({ insight, date_from }) => insight === ViewType.LIFECYCLE || date_from === 'all',
        ],
    },

    listeners: ({ actions, values }) => ({
        setCompare: ({ compare }) => {
            actions.setFilters({ ...values.filters, compare })
        },
        toggleCompare: () => {
            actions.setFilters({ ...values.filters, compare: !values.compare })
        },
    }),
})
