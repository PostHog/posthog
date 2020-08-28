import { kea } from 'kea'
import { cleanFunnelParams } from './funnelLogic'
import { pollFunnel } from './funnelLogic'

export const funnelVizLogic = kea({
    key: (props) => props.dashboardItemId || 'some_funnel',
    loaders: ({ props }) => ({
        results: {
            __default: [],
            loadResults: async (refresh = false) => {
                const { from_dashboard } = props.filters
                const cleanedParams = cleanFunnelParams(props.filters)
                const params = {
                    ...(refresh ? { refresh: true } : {}),
                    ...(from_dashboard ? { from_dashboard } : {}),
                    ...cleanedParams,
                }
                return await pollFunnel(params)
            },
        },
        trendsResults: {
            loadTrends: async (refresh = false) => {
                const response = await api.get(
                    'api/funnel/' + props.funnelId + '/?display=FunnelTrends' + (refresh ? '&refresh=true' : '')
                )
                return response.trends
            },
        },
    }),
})
