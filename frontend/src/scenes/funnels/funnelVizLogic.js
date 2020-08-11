import { kea } from 'kea'
import api from 'lib/api'

export const funnelVizLogic = kea({
    key: (props) => props.dashboardItemId || 'some_funnel',
    loaders: ({ props }) => ({
        results: {
            loadResults: async (refresh = false) => {
                const { from_dashboard } = props.filters
                let response = await api.get(
                    'api/funnel/' +
                        props.funnelId +
                        '/?' +
                        (refresh ? 'refresh=true' : '') +
                        (from_dashboard ? '&from_dashboard=' + from_dashboard : '')
                )
                return response
            },
        },
    }),
})
