import { kea } from 'kea'
import type { insightDateFilterLogicType } from './insightDateFilterLogicType'
import { InsightLogicProps } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

export const insightDateFilterLogic = kea<insightDateFilterLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['scenes', 'insights', 'InsightDateFilter', 'insightDateFilterLogic', key],
    connect: (props: InsightLogicProps) => ({
        actions: [insightLogic(props), ['setFilters'], insightDataLogic(props), ['setQuery']],
        values: [insightLogic(props), ['filters'], insightDataLogic(props), ['query']],
    }),
    actions: () => ({
        setDates: (dateFrom: string | undefined | null, dateTo: string | undefined | null) => ({
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
            actions.setQuery({
                ...values.query,
                source: {
                    ...values.query.source,
                    dateRange: {
                        date_from: dateFrom || null,
                        date_to: dateTo || null,
                    },
                },
            })
        },
    }),
})
