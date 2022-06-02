import { kea } from 'kea'
import { objectsEqual } from 'lib/utils'
import type { intervalFilterLogicType } from './intervalFilterLogicType'
import { IntervalKeyType } from 'lib/components/IntervalFilter/intervals'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightLogicProps } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

export const intervalFilterLogic = kea<intervalFilterLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['lib', 'components', 'IntervalFilter', 'intervalFilterLogic', key],
    connect: (props: InsightLogicProps) => ({
        actions: [insightLogic(props), ['setFilters']],
        values: [insightLogic(props), ['filters']],
    }),
    actions: () => ({
        setInterval: (interval: IntervalKeyType) => ({ interval }),
    }),
    listeners: ({ values, actions }) => ({
        setInterval: ({ interval }) => {
            if (!objectsEqual(interval, values.filters.interval)) {
                actions.setFilters({ ...values.filters, interval })
            }
        },
    }),
    selectors: {
        interval: [(s) => [s.filters], (filters) => filters?.interval],
    },
})
