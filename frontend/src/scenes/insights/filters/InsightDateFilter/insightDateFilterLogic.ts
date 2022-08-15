import { kea } from 'kea'
import type { insightDateFilterLogicType } from './insightDateFilterLogicType'
import { InsightLogicProps } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

export const insightDateFilterLogic = kea<insightDateFilterLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['scenes', 'insights', 'InsightDateFilter', 'insightDateFilterLogic', key],
    connect: (props: InsightLogicProps) => ({
        actions: [insightLogic(props), ['setFilters']],
        values: [insightLogic(props), ['filters']],
    }),
    actions: () => ({
        setDates: (dateFrom: string | undefined, dateTo: string | undefined) => ({
            dateFrom,
            dateTo,
        }),
    }),
    selectors: {
        dates: [
            (s) => [s.filters],
            (filters) => ({ dateFrom: filters?.date_from || null, dateTo: filters?.date_to || null }),
        ],
    },
    listeners: ({ actions, values }) => ({
        setDates: ({ dateFrom, dateTo }) => {
            actions.setFilters({
                ...values.filters,
                date_from: dateFrom || null,
                date_to: dateTo || null,
            })
        },
    }),
})
