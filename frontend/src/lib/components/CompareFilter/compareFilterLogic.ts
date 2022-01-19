import { kea } from 'kea'
import { objectsEqual } from 'lib/utils'
import { InsightLogicProps, InsightType } from '~/types'
import { compareFilterLogicType } from './compareFilterLogicType'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightLogic } from 'scenes/insights/insightLogic'

export const compareFilterLogic = kea<compareFilterLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['lib', 'components', 'CompareFilter', 'compareFilterLogic', key],
    connect: (props: InsightLogicProps) => ({
        actions: [insightLogic(props), ['setFilters']],
        values: [insightLogic(props), ['filters']],
    }),

    actions: () => ({
        setCompare: (compare: boolean) => ({ compare }),
        toggleCompare: true,
    }),

    selectors: {
        compare: [(s) => [s.filters], (filters) => !!filters?.compare],
        disabled: [
            (s) => [s.filters],
            ({ insight, date_from }) => insight === InsightType.LIFECYCLE || date_from === 'all',
        ],
    },

    listeners: ({ values, actions }) => ({
        setCompare: ({ compare }) => {
            if (!objectsEqual(compare, values.compare)) {
                actions.setFilters({ ...values.filters, compare })
            }
        },
        toggleCompare: () => {
            actions.setCompare(!values.compare)
        },
    }),
})
