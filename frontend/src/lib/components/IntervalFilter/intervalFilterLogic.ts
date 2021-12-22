import { kea } from 'kea'
import { objectsEqual } from 'lib/utils'
import { intervalFilterLogicType } from './intervalFilterLogicType'
import { IntervalKeyType } from 'lib/components/IntervalFilter/intervals'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightLogicProps } from '~/types'

export const intervalFilterLogic = kea<intervalFilterLogicType>({
    props: {} as InsightLogicProps,
    path: ['lib', 'components', 'IntervalFilter', 'intervalFilterLogic'],
    actions: () => ({
        setInterval: (interval: IntervalKeyType) => ({ interval }),
    }),
    connect: (props: InsightLogicProps) => ({
        actions: [insightLogic(props), ['setFilters']],
        values: [insightLogic(props), ['filters']],
    }),
    listeners: ({ values, actions }) => ({
        setInterval: ({ interval }) => {
            if (!objectsEqual(interval, values.filters.interval)) {
                actions.setFilters({ ...values.filters, interval })
            }
        },
    }),
    selectors: {
        interval: [
            (s) => [s.filters],
            (filters) => {
                return filters?.interval
            },
        ],
    },
})
