import { kea } from 'kea'
import { insightDateFilterLogicType } from './insightDateFilterLogicType'
import { InsightLogicProps } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

export const insightDateFilterLogic = kea<insightDateFilterLogicType>({
    props: {} as InsightLogicProps,
    path: ['scenes', 'insights', 'InsightDateFilter', 'insightDateFilterLogic'],
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
    listeners: ({ actions }) => ({
        setDates: ({ dateFrom, dateTo }) => {
            actions.setFilters({
                date_from: dateFrom || null,
                date_to: dateTo || null,
            })
        },
    }),
})
