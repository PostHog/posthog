import { kea } from 'kea'
import { router } from 'kea-router'
import { objectsEqual } from 'lib/utils'

export const intervalFilterLogic = kea({
    actions: () => ({
        setIntervalFilter: (filter) => ({ filter }),
        setDateFrom: (dateFrom) => ({ dateFrom }),
    }),
    reducers: ({ actions }) => ({
        interval: [
            null,
            {
                [actions.setIntervalFilter]: (_, { filter }) => filter,
            },
        ],
        dateFrom: [
            null,
            {
                [actions.setDateFrom]: (_, { dateFrom }) => dateFrom,
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        [actions.setIntervalFilter]: () => {
            const { properties: _, ...searchParams } = router.values.searchParams // eslint-disable-line
            const { pathname } = router.values.location

            searchParams.interval = values.interval

            if (!objectsEqual(router.values.searchParams, searchParams)) {
                router.actions.push(pathname, searchParams)
            }
        },
        [actions.setDateFrom]: () => {
            const { properties: _, ...searchParams } = router.values.searchParams // eslint-disable-line
            const { pathname } = router.values.location

            searchParams.date_from = values.dateFrom

            if (!objectsEqual(router.values.searchParams, searchParams)) {
                router.actions.push(pathname, searchParams)
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '*': (_, { interval, date_from }) => {
            if (interval) actions.setIntervalFilter(interval)
            if (date_from) actions.setDateFrom(date_from)
        },
    }),
})
