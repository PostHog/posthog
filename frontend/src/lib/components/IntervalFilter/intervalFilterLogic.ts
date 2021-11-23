import { kea } from 'kea'
import { intervalFilterLogicType } from './intervalFilterLogicType'
import { IntervalKeyType } from 'lib/components/IntervalFilter/intervals'
import { InsightLogicProps } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

export const intervalFilterLogic = kea<intervalFilterLogicType>({
    path: ['lib', 'components', 'IntervalFilter', 'intervalFilterLogic'],
    props: {} as InsightLogicProps,
    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters']],
        actions: [insightLogic(props), ['setFilters']],
    }),
    actions: () => ({
        setIntervalFilter: (interval: IntervalKeyType) => ({ interval }),
        setDateFrom: (dateFrom: string) => ({ dateFrom }),
    }),
    listeners: ({ actions, values }) => ({
        setIntervalFilter: ({ interval }) => {
            actions.setFilters({
                ...values.filters,
                interval: interval,
            })
        },
        setDateFrom: ({ dateFrom }) => {
            actions.setFilters({
                ...values.filters,
                date_from: dateFrom,
            })
        },
    }),
})
