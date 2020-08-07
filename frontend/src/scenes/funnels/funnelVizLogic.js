import { kea } from 'kea'
import { cleanFunnelParams } from './funnelLogic'
import { pollFunnel } from './funnelLogic'

export const funnelVizLogic = kea({
    key: (props) => props.dashboardItemId || 'some_funnel',
    loaders: ({ props }) => ({
        results: {
            __default: [],
            loadResults: async () => {
                const cleanedParams = cleanFunnelParams(props.filters)
                return await pollFunnel(cleanedParams)
            },
        },
    }),
})
