import { kea } from 'kea'
import { router } from 'kea-router'
import dayjs from 'dayjs'
import { dateFilterLogicType } from 'scenes/insights/DateFilter/dateFilterLogicType'
import { objectsEqual } from 'lib/utils'

type Dayjs = dayjs.Dayjs

interface UrlParams {
    date_from?: string
    date_to?: string
}

export const dateFilterLogic = kea<dateFilterLogicType<UrlParams, Dayjs>>({
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

            if (
                (pathname === '/insights' && !objectsEqual(date_from, values.dates.dateFrom)) ||
                !objectsEqual(date_to, values.dates.dateTo)
            ) {
                router.actions.push(pathname, searchParams)
            }
        },
        dateAutomaticallyChanged: async (_, breakpoint) => {
            await breakpoint(2000)
            actions.endHighlightChange()
        },
    }),
    urlToAction: ({ actions, values }) => ({
        '/insights': (_: any, { date_from, date_to }: UrlParams) => {
            if (!values.initialLoad && !objectsEqual(date_from, values.dates.dateFrom)) {
                actions.dateAutomaticallyChanged()
            }
            actions.setDates(date_from, date_to)
            actions.setInitialLoad()
        },
    }),
})
