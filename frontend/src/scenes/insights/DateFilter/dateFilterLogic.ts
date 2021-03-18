import { kea } from 'kea'
import { router } from 'kea-router'
import * as dayjs from 'dayjs'
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
    }),
    listeners: ({ values }) => ({
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
    }),
    urlToAction: ({ actions }) => ({
        '/insights': (_: any, { date_from, date_to }: UrlParams) => {
            actions.setDates(date_from, date_to)
        },
    }),
})
