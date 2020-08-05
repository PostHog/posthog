import { kea } from 'kea'
import { pollFunnel } from './funnelLogic'

export const funnelVizLogic = kea({
    key: (props) => props.dashboardItemId || 'some_funnel',
    loaders: ({ props }) => ({
        results: {
            loadResults: async (refresh = false) => {
                const { from_dashboard } = props.filters
                let params = {
                    ...(refresh ? { refresh: true } : {}),
                    ...(from_dashboard ? { from_dashboard } : {}),
                }
                return await pollFunnel(props.funnelId, params)
            },
        },
    }),
})
