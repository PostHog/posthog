import { kea } from 'kea'
import api from 'lib/api'

export const funnelVizLogic = kea({
    key: (props) => props.dashboardItemId || 'some_funnel',
    loaders: ({ props }) => ({
        stepsResults: {
            loadSteps: async (refresh = false) => {
                const { from_dashboard } = props.filters
                const response = await api.get(
                    'api/funnel/' +
                        props.funnelId +
                        '/?display=FunnelSteps' +
                        (refresh ? '&refresh=true' : '') +
                        (from_dashboard ? '&from_dashboard=' + from_dashboard : '')
                )
                return response
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
