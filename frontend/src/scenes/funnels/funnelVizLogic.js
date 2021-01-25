import { kea } from 'kea'
import { cleanFunnelParams } from './funnelLogic'
import { pollFunnel } from './funnelLogic'

export const funnelVizLogic = kea({
    key: (props) => props.dashboardItemId || 'some_funnel',
    loaders: ({ props }) => ({
        results: {
            __default: [],
            // TODO BEFORE COMMITTING SET REFRESH TO FALSE
            loadResults: async (refresh = true) => {
                if (!refresh && props.cachedResults) {
                    return props.cachedResults
                }
                const { from_dashboard } = props.filters
                const cleanedParams = cleanFunnelParams(props.filters)
                refresh = true
                const params = {
                    ...(refresh ? { refresh: true } : {}),
                    ...(from_dashboard ? { from_dashboard } : {}),
                    ...cleanedParams,
                }
                return await pollFunnel(params)
            },
        },
    }),
})
