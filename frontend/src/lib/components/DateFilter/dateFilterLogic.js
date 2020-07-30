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
            const { date_from, date_to, ...searchParams } = router.values.searchParams // eslint-disable-line
            const { pathname } = router.values.location

            searchParams.date_from = values.dates.dateFrom
            searchParams.date_to = values.dates.dateTo

            if (!objectsEqual(date_from, values.dates.dateFrom) || !objectsEqual(date_to, values.dates.dateTo)) {
                router.actions.push(pathname, searchParams)
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '/insights': (_, { date_from, date_to }) => {
            actions.setDates(date_from, date_to)
        },
    }),
})
