import { kea } from 'kea'
import { router } from 'kea-router'
import { objectsEqual } from 'lib/utils'
import { insightDateFilterLogicType } from './insightDateFilterLogicType'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightLogicProps } from '~/types'

export const insightDateFilterLogic = kea<insightDateFilterLogicType>({
    props: {} as InsightLogicProps,
    path: ['scenes', 'insights', 'InsightDateFilter', 'insightDateFilterLogic'],
    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters', 'fallbackDateRange']],
    }),
    actions: () => ({
        dateAutomaticallyChanged: true,
        endHighlightChange: true,
        setInitialLoad: true,
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
    reducers: () => ({
        highlightDateChange: [
            false,
            {
                dateAutomaticallyChanged: () => true,
                endHighlightChange: () => false,
            },
        ],
        initialLoad: [
            true,
            {
                setInitialLoad: () => false,
            },
        ],
    }),
    listeners: ({ values, actions }) => ({
        setDates: () => {
            const { date_from, date_to, ...searchParams } = router.values.searchParams // eslint-disable-line
            const { pathname } = router.values.location

            searchParams.date_from = values.dates.dateFrom
            searchParams.date_to = values.dates.dateTo

            if (
                (pathname.startsWith('/insights/') && !objectsEqual(date_from, values.dates.dateFrom)) ||
                !objectsEqual(date_to, values.dates.dateTo)
            ) {
                router.actions.replace(pathname, searchParams, router.values.hashParams)
            }
        },
        dateAutomaticallyChanged: async (_, breakpoint) => {
            await breakpoint(2000)
            actions.endHighlightChange()
        },
    }),
})
