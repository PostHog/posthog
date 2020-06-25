import { kea } from 'kea'
import api from 'lib/api'

export const funnelVizLogic = kea({
    key: props => props.dashboardItemId || 'some_funnel',
    loaders: ({ props }) => ({
        results: {
            loadResults: async (refresh = false) => {
                const { funnel_id, from_dashboard } = props.filters
                let response = await api.get(
                    'api/funnel/' +
                        funnel_id +
                        '/?' +
                        (refresh ? 'refresh=true' : '') +
                        (from_dashboard ? '&from_dashboard=' + from_dashboard : '')
                )
                return response
            },
        },
    }),
})
