import { kea } from 'kea'
import { router } from 'kea-router'
import { objectsEqual } from 'lib/utils'
import { intervalFilterLogicType } from './intervalFilterLogicType'
import { IntervalKeyType } from 'lib/components/IntervalFilter/intervals'

export const intervalFilterLogic = kea<intervalFilterLogicType>({
    actions: () => ({
        setIntervalFilter: (filter: IntervalKeyType) => ({ filter }),
        setDateFrom: (dateFrom: string) => ({ dateFrom }),
    }),
    reducers: {
        interval: [
            null as null | IntervalKeyType,
            {
                setIntervalFilter: (_, { filter }) => filter,
            },
        ],
        dateFrom: [
            null as null | string,
            {
                setDateFrom: (_, { dateFrom }) => dateFrom,
            },
        ],
    },
    listeners: ({ values }) => ({
        setIntervalFilter: () => {
            const { interval, ...searchParams } = router.values.searchParams
            const { pathname } = router.values.location

            searchParams.interval = values.interval

            if (!objectsEqual(interval, values.interval)) {
                router.actions.replace(pathname, searchParams, router.values.hashParams)
            }
        },
        setDateFrom: () => {
            const { date_from, ...searchParams } = router.values.searchParams
            const { pathname } = router.values.location

            searchParams.date_from = values.dateFrom

            if (!objectsEqual(date_from, values.dateFrom)) {
                router.actions.replace(pathname, searchParams, router.values.hashParams)
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '/insights': (_, { interval, date_from }) => {
            if (interval) {
                actions.setIntervalFilter(interval)
            }
            if (date_from) {
                actions.setDateFrom(date_from)
            }
        },
    }),
})
