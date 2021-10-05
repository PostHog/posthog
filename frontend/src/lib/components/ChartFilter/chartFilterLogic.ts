import { kea } from 'kea'
import { router } from 'kea-router'
import { objectsEqual } from 'lib/utils'
import { chartFilterLogicType } from './chartFilterLogicType'
import { ChartDisplayType, FilterType, FunnelVizType, ViewType } from '~/types'

function isFunnelVizType(filter: FunnelVizType | ChartDisplayType): filter is FunnelVizType {
    return Object.values(FunnelVizType).includes(filter as FunnelVizType)
}

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
            const { display, funnel_viz_type, ..._params }: Partial<FilterType> = {
                ...router.values.searchParams,
                ...router.values.hashParams,
            } // eslint-disable-line
            const { pathname } = router.values.location

            const hashParams = _params as Partial<FilterType>
            if (isFunnelVizType(filter)) {
                hashParams.funnel_viz_type = filter
                hashParams.display = ChartDisplayType.FunnelViz
            } else {
                hashParams.display = values.chartFilter as ChartDisplayType
            }
            if (
                (!isFunnelVizType(filter) && !objectsEqual(display, values.chartFilter)) ||
                (isFunnelVizType(filter) && !objectsEqual(funnel_viz_type, values.chartFilter))
            ) {
                router.actions.replace(pathname, {}, hashParams)
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '/insights': (_, searchParams, hashParams) => {
            const { display, insight, funnel_viz_type }: Partial<FilterType> = { ...searchParams, ...hashParams.q }
            if (display === ChartDisplayType.FunnelViz && !funnel_viz_type) {
                actions.setChartFilter(FunnelVizType.Steps)
            } else if (display && !funnel_viz_type) {
                actions.setChartFilter(display)
            } else if (insight === ViewType.RETENTION) {
                actions.setChartFilter(ChartDisplayType.ActionsTable)
            } else if (insight === ViewType.FUNNELS) {
                actions.setChartFilter((funnel_viz_type as FunnelVizType) || FunnelVizType.Steps)
            }
        },
    }),
})
