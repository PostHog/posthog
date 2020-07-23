import { kea } from 'kea'
import { ACTIONS_LINE_GRAPH_LINEAR } from '~/lib/constants'
import { router } from 'kea-router'
import { objectsEqual } from 'lib/utils'

export const chartFilterLogic = kea({
    actions: () => ({
        setChartFilter: (filter) => ({ filter }),
    }),
    reducers: ({ actions }) => ({
        chartFilter: [
            ACTIONS_LINE_GRAPH_LINEAR,
            {
                [actions.setChartFilter]: (_, { filter }) => filter,
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        [actions.setChartFilter]: () => {
            const { properties: _, ...searchParams } = router.values.searchParams // eslint-disable-line
            const { pathname } = router.values.location

            searchParams.display = values.chartFilter

            if (!objectsEqual(router.values.searchParams, searchParams)) {
                router.actions.push(pathname, searchParams)
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '*': (_, { display }) => {
            if (display) actions.setChartFilter(display)
        },
    }),
})
