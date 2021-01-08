import { kea } from 'kea'
import { ACTIONS_LINE_GRAPH_LINEAR, ACTIONS_TABLE } from '~/lib/constants'
import { router } from 'kea-router'
import { objectsEqual } from 'lib/utils'
import { ViewType } from 'scenes/insights/insightLogic'

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
            const { display, ...searchParams } = router.values.searchParams // eslint-disable-line
            const { pathname } = router.values.location

            searchParams.display = values.chartFilter

            if (!objectsEqual(display, values.chartFilter)) {
                router.actions.push(pathname, searchParams)
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '/insights': (_, { display, insight }) => {
            if (display) {
                actions.setChartFilter(display)
            } else if (insight === ViewType.RETENTION) {
                actions.setChartFilter(ACTIONS_TABLE)
            }
        },
    }),
})
