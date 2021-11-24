import { kea } from 'kea'
import { router } from 'kea-router'
import { objectsEqual } from 'lib/utils'
import { chartFilterLogicType } from './chartFilterLogicType'
import { ChartDisplayType, FunnelVizType, InsightType } from '~/types'

function isFunnelVizType(filter: FunnelVizType | ChartDisplayType): filter is FunnelVizType {
    return Object.values(FunnelVizType).includes(filter as FunnelVizType)
}

export const chartFilterLogic = kea<chartFilterLogicType>({
    path: ['lib', 'components', 'ChartFilter', 'chartFilterLogic'],
    actions: () => ({
        setChartFilter: (filter: ChartDisplayType | FunnelVizType) => ({ filter }),
        chartAutomaticallyChanged: true,
        endHighlightChange: true,
        setInitialLoad: true,
    }),
    reducers: {
        chartFilter: [
            null as null | ChartDisplayType | FunnelVizType,
            {
                setChartFilter: (_, { filter }) => filter,
            },
        ],
        highlightChartChange: [
            false,
            {
                chartAutomaticallyChanged: () => true,
                endHighlightChange: () => false,
            },
        ],
        initialLoad: [
            true,
            {
                setInitialLoad: () => false,
            },
        ],
    },
    listeners: ({ actions, values }) => ({
        setChartFilter: ({ filter }) => {
            const { display, funnel_viz_type, ...searchParams } = router.values.searchParams // eslint-disable-line
            const { pathname } = router.values.location
            if (isFunnelVizType(filter)) {
                searchParams.funnel_viz_type = filter
                searchParams.display = ChartDisplayType.FunnelViz
            } else {
                searchParams.display = values.chartFilter
            }
            if (
                (!isFunnelVizType(filter) && !objectsEqual(display, values.chartFilter)) ||
                (isFunnelVizType(filter) && !objectsEqual(funnel_viz_type, values.chartFilter))
            ) {
                router.actions.replace(pathname, searchParams, router.values.hashParams)
            }
        },
        chartAutomaticallyChanged: async (_, breakpoint) => {
            await breakpoint(2000)
            actions.endHighlightChange()
        },
    }),
    urlToAction: ({ actions, values }) => ({
        '/insights': (_, { display, insight, funnel_viz_type }) => {
            if (!values.initialLoad && !objectsEqual(display, values.chartFilter)) {
                actions.chartAutomaticallyChanged()
            }
            if (display === ChartDisplayType.FunnelViz && !funnel_viz_type) {
                actions.setChartFilter(FunnelVizType.Steps)
            } else if (display && !funnel_viz_type) {
                actions.setChartFilter(display)
            } else if (insight === InsightType.RETENTION) {
                actions.setChartFilter(ChartDisplayType.ActionsTable)
            } else if (insight === InsightType.FUNNELS) {
                actions.setChartFilter(funnel_viz_type || FunnelVizType.Steps)
            } else if (insight === InsightType.TRENDS) {
                actions.setChartFilter(ChartDisplayType.ActionsLineGraphLinear)
            }
            actions.setInitialLoad()
        },
    }),
})
