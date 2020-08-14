import { kea } from 'kea'
import api from 'lib/api'

export const funnelVizLogic = kea({
    key: (props) => props.dashboardItemId || 'some_funnel',
    loaders: ({ props }) => ({
        stepsResults: {
            loadResults: async (refresh = false) => {
                const { from_dashboard } = props.filters
                let response = await api.get(
                    'api/funnel/' +
                        props.funnelId +
                        '/?display=FunnelSteps&' +
                        (refresh ? 'refresh=true' : '') +
                        (from_dashboard ? '&from_dashboard=' + from_dashboard : '')
                )
                return response
            },
        },
        trendsResults: {
            loadResults: async (refresh = false) => {
                const { from_dashboard } = props.filters
                let response = await api.get(
                    'api/funnel/' +
                        props.funnelId +
                        '/?display=FunnelTrends&' +
                        (refresh ? 'refresh=true' : '') +
                        (from_dashboard ? '&from_dashboard=' + from_dashboard : '')
                )
                return response
            },
        },
    }),
})
