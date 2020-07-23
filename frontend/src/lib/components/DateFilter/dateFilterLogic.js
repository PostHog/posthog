import { kea } from 'kea'
import { router } from 'kea-router'
import { objectsEqual } from 'lib/utils'

export const dateFilterLogic = kea({
    actions: () => ({
        setDates: (dateFrom, dateTo) => ({ dateFrom, dateTo }),
    }),
    reducers: ({ actions }) => ({
        dates: [
            {},
            {
                [actions.setDates]: (_, dates) => dates,
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        [actions.setDates]: () => {
            const { properties: _, ...searchParams } = router.values.searchParams // eslint-disable-line
            const { pathname } = router.values.location

            searchParams.date_from = values.dates.dateFrom
            searchParams.date_to = values.dates.dateTo

            if (!objectsEqual(router.values.searchParams, searchParams)) {
                router.actions.push(pathname, searchParams)
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '*': (_, { date_from, date_to }) => {
            actions.setDates(date_from, date_to)
        },
    }),
})
