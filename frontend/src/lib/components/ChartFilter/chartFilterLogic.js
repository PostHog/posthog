import { kea } from 'kea'
import { ACTIONS_BAR_CHART, ACTIONS_LINE_GRAPH_LINEAR, ACTIONS_TABLE } from '~/lib/constants'
import { router } from 'kea-router'
import { objectsEqual } from 'lib/utils'
import { ViewType } from 'scenes/insights/insightLogic'

export const chartFilterLogic = kea({
    actions: () => ({
        setChartFilter: (filter) => ({ filter }),
        setDisabled: (disabled) => ({ disabled }),
    }),
    reducers: ({ actions }) => ({
        chartFilter: [
            ACTIONS_LINE_GRAPH_LINEAR,
            {
                [actions.setChartFilter]: (_, { filter }) => filter,
            },
        ],
        disabled: [
            false,
            {
                [actions.setDisabled]: (_, { disabled }) => disabled,
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
        '/insights': (_, { display, insight, shown_as }) => {
            if (display) {
                actions.setChartFilter(display)
            } else if (insight === ViewType.RETENTION) {
                actions.setChartFilter(ACTIONS_TABLE)
            }
            if (shown_as === 'Lifecycle') {
                actions.setChartFilter(ACTIONS_BAR_CHART)
                actions.setDisabled(true)
            } else {
                actions.setDisabled(false)
            }
        },
    }),
})
