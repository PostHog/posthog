import { kea } from 'kea'
import { objectsEqual } from 'lib/utils'
import { ChartDisplayType, InsightLogicProps, InsightType, TrendsFilterType } from '~/types'
import type { compareFilterLogicType } from './compareFilterLogicType'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { isTrendsFilter } from 'scenes/insights/sharedUtils.ts'

export const compareFilterLogic = kea<compareFilterLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['lib', 'components', 'CompareFilter', 'compareFilterLogic', key],
    connect: (props: InsightLogicProps) => ({
        actions: [insightLogic(props), ['setFilters']],
        values: [insightLogic(props), ['filters', 'canEditInsight']],
    }),

    actions: () => ({
        setCompare: (compare: boolean) => ({ compare }),
        toggleCompare: true,
    }),

    selectors: {
        compare: [(s) => [s.filters], (filters) => filters && isTrendsFilter(filters) && !!filters.compare],
        disabled: [
            (s) => [s.filters, s.canEditInsight],
            ({ insight, date_from, display }, canEditInsight) =>
                !canEditInsight ||
                insight === InsightType.LIFECYCLE ||
                display === ChartDisplayType.WorldMap ||
                date_from === 'all',
        ],
    },

    listeners: ({ values, actions }) => ({
        setCompare: ({ compare }) => {
            if (!objectsEqual(compare, values.compare)) {
                const newFilters: Partial<TrendsFilterType> = { ...values.filters, compare }
                actions.setFilters(newFilters)
            }
        },
        toggleCompare: () => {
            actions.setCompare(!values.compare)
        },
    }),
})
