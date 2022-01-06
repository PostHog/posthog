import { kea } from 'kea'
import { router } from 'kea-router'
import { Dayjs } from 'dayjs'
import { objectsEqual } from 'lib/utils'
import { insightDateFilterLogicType } from './insightDateFilterLogicType'
import { ChartDisplayType } from '~/types'

interface UrlParams {
    date_from?: string
    date_to?: string
}

export const insightDateFilterLogic = kea<insightDateFilterLogicType>({
    path: ['scenes', 'insights', 'InsightDateFilter', 'insightDateFilterLogic'],
    actions: () => ({
        setDates: (dateFrom: string | Dayjs | undefined, dateTo: string | Dayjs | undefined) => ({
            dateFrom,
            dateTo,
        }),
        dateAutomaticallyChanged: true,
        endHighlightChange: true,
        setInitialLoad: true,
    }),
    reducers: () => ({
        dates: [
            {
                dateFrom: undefined as string | Dayjs | undefined,
                dateTo: undefined as string | Dayjs | undefined,
            },
            {
                setDates: (_, dates) => dates,
            },
        ],
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

            if (values.dates.dateFrom === values.dates.dateTo || values.dates.dateFrom === 'dStart') {
                // If viewing a single data point (yesterday or today), change to bar chart as the line chart will look empty
                searchParams.display = ChartDisplayType.ActionsBarChart
            }

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
    urlToAction: ({ actions, values }) => ({
        '/insights/:shortId(/edit)': (_: any, { date_from, date_to }: UrlParams) => {
            if (!values.initialLoad && !objectsEqual(date_from, values.dates.dateFrom)) {
                actions.dateAutomaticallyChanged()
            }
            actions.setDates(date_from, date_to)
            actions.setInitialLoad()
        },
    }),
})
