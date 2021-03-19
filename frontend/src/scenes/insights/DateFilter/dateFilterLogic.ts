import { kea } from 'kea'
import { router } from 'kea-router'
import dayjs from 'dayjs'
import { dateFilterLogicType } from 'scenes/insights/DateFilter/dateFilterLogicType'
import { objectsEqual } from 'lib/utils'

type Dayjs = dayjs.Dayjs

interface UrlParams {
    date_from?: string
    date_to?: string
    date_auto_changed?: boolean
}

export const dateFilterLogic = kea<dateFilterLogicType<UrlParams, Dayjs>>({
    actions: () => ({
        setDates: (dateFrom: string | Dayjs | undefined, dateTo: string | Dayjs | undefined) => ({
            dateFrom,
            dateTo,
        }),
        setDateAutoChanged: (dateAutoChanged: boolean) => ({ dateAutoChanged }),
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
        dateAutoChanged: [
            false,
            {
                setDateAutoChanged: (_, { dateAutoChanged }) => dateAutoChanged,
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
        setDateAutoChanged: async ({ dateAutoChanged }, breakpoint) => {
            if (dateAutoChanged) {
                await breakpoint(2000)
                const { searchParams, location } = router.values
                router.actions.push(location.pathname, { ...searchParams, date_auto_changed: undefined }) // remove it immediately from query string
                actions.setDateAutoChanged(false)
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '/insights': (_: any, { date_from, date_to, date_auto_changed }: UrlParams) => {
            actions.setDates(date_from, date_to)
            console.log(date_auto_changed)
            actions.setDateAutoChanged(!!date_auto_changed)
        },
    }),
})
