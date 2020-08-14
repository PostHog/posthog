import { kea } from 'kea'
import { ACTIONS_LINE_GRAPH_LINEAR, FUNNEL_STEPS } from '~/lib/constants'
import { router } from 'kea-router'
import { objectsEqual } from 'lib/utils'

export const chartFilterLogic = kea({
    actions: () => ({
        setChartFilterTrends: (filter) => ({ filter }),
        setChartFilterFunnels: (filter) => ({ filter }),
    }),
    reducers: ({ actions }) => ({
        chartFilterTrends: [
            ACTIONS_LINE_GRAPH_LINEAR,
            {
                [actions.setChartFilterTrends]: (_, { filter }) => filter,
            },
        ],
        chartFilterFunnels: [
            FUNNEL_STEPS,
            {
                [actions.setChartFilterFunnels]: (_, { filter }) => filter,
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        [actions.setChartFilterTrends]: () => {
            const { display, ...searchParams } = router.values.searchParams // eslint-disable-line
            const { pathname } = router.values.location

            searchParams.display = values.chartFilterTrends

            if (!objectsEqual(display, values.chartFilterTrends)) {
                router.actions.push(pathname, searchParams)
            }
        },
        [actions.setChartFilterFunnels]: () => {
            const { display, ...searchParams } = router.values.searchParams // eslint-disable-line
            const { pathname } = router.values.location

            searchParams.display = values.chartFilterFunnels

            if (!objectsEqual(display, values.chartFilterFunnels)) {
                router.actions.push(pathname, searchParams)
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '/insights': (_, { insight, display }) => {
            if (display) {
                if (insight === 'FUNNELS') actions.setChartFilterFunnels(display)
                else actions.setChartFilterTrends(display)
            }
        },
    }),
})
