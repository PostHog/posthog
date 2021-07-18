import { kea } from 'kea'
import { router } from 'kea-router'
import { objectsEqual } from 'lib/utils'
import { chartFilterLogicType } from './chartFilterLogicType'
import { ChartDisplayType, FunnelVizType, ViewType } from '~/types'

export const chartFilterLogic = kea<chartFilterLogicType>({
    actions: () => ({
        setChartFilter: (filter: ChartDisplayType | FunnelVizType) => ({ filter }),
    }),
    reducers: {
        chartFilter: [
            null as null | ChartDisplayType | FunnelVizType,
            {
                setChartFilter: (_, { filter }) => filter,
            },
        ],
    },
    listeners: ({ values }) => ({
        setChartFilter: ({ filter }) => {
            const { display, funnel_viz_type, ...searchParams } = router.values.searchParams // eslint-disable-line
            const { pathname } = router.values.location
            const isFunnelVizType = filter === 'steps' || filter === 'time_to_convert' || filter === 'trends'
            if (isFunnelVizType) {
                searchParams.funnel_viz_type = filter
                searchParams.display = ChartDisplayType.FunnelViz
            } else {
                searchParams.display = values.chartFilter
            }
            if (
                (!isFunnelVizType && !objectsEqual(display, values.chartFilter)) ||
                (isFunnelVizType && !objectsEqual(funnel_viz_type, values.chartFilter))
            ) {
                router.actions.replace(pathname, searchParams)
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '/insights': (_, { display, insight, funnel_viz_type }) => {
            if (display && !funnel_viz_type) {
                actions.setChartFilter(display)
            } else if (insight === ViewType.RETENTION) {
                actions.setChartFilter(ChartDisplayType.ActionsTable)
            } else if (insight === ViewType.FUNNELS) {
                actions.setChartFilter(funnel_viz_type)
            }
        },
    }),
})
