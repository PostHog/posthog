import { kea } from 'kea'
import { insightDateFilterLogicType } from './insightDateFilterLogicType'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightLogicProps } from '~/types'

export const insightDateFilterLogic = kea<insightDateFilterLogicType>({
    props: {} as InsightLogicProps,
    path: ['scenes', 'insights', 'InsightDateFilter', 'insightDateFilterLogic'],
    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters', 'fallbackDateRange']],
        actions: [insightLogic(props), ['setFilters']],
    }),
    actions: () => ({
        setDates: (date_from: string, date_to: string) => ({ date_from, date_to }),
    }),
    selectors: {
        dates: [
            (selectors) => [selectors.filters, selectors.fallbackDateRange],
            (filters, fallbackDateRange) => {
                return {
                    dateFrom: filters.date_from ?? fallbackDateRange.dateFrom,
                    dateTo: filters.date_from ? filters.date_to : filters.date_to ?? fallbackDateRange.dateTo,
                }
            },
        ],
    },
    listeners: ({ values, actions }) => ({
        setDates: (dateFilter) => {
            if (dateFilter.date_from !== values.filters?.date_from || dateFilter.date_to !== values.filters?.date_to) {
                actions.setFilters({ ...values.filters, ...dateFilter })
            }
        },
    }),
})
