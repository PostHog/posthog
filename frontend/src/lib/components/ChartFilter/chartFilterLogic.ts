import { kea } from 'kea'
import { router } from 'kea-router'
import { objectsEqual } from 'lib/utils'
import { ViewType } from 'scenes/insights/insightLogic'
import { chartFilterLogicType } from './chartFilterLogicType'
import { ChartDisplayType } from '~/types'

export const chartFilterLogic = kea<chartFilterLogicType>({
    actions: () => ({
        setChartFilter: (filter: ChartDisplayType) => ({ filter }),
    }),
    reducers: {
        chartFilter: [
            null as null | ChartDisplayType,
            {
                setChartFilter: (_, { filter }) => filter,
            },
        ],
    },
    listeners: ({ values }) => ({
        setChartFilter: () => {
            const { display, ...searchParams } = router.values.searchParams // eslint-disable-line
            const { pathname } = router.values.location
            searchParams.display = values.chartFilter

            if (!objectsEqual(display, values.chartFilter)) {
                router.actions.replace(pathname, searchParams)
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '/insights': (_, { display, insight }) => {
            if (display) {
                actions.setChartFilter(display)
            } else if (insight === ViewType.RETENTION) {
                actions.setChartFilter(ChartDisplayType.ActionsTable)
            } else if (insight === ViewType.FUNNELS) {
                if (display === ChartDisplayType.FunnelsHistogram) {
                    actions.setChartFilter(ChartDisplayType.FunnelsHistogram)
                } else {
                    actions.setChartFilter(ChartDisplayType.FunnelViz)
                }
            }
        },
    }),
})
