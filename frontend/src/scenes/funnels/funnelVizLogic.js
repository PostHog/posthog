import { kea } from 'kea'
import api from 'lib/api'
import { cleanFunnelParams } from './funnelLogic'
import { toParams } from 'lib/utils'

export const funnelVizLogic = kea({
    key: (props) => props.dashboardItemId || 'some_funnel',
    loaders: ({ props }) => ({
        results: {
            __default: [],
            loadResults: async () => {
                const urlParams = toParams(cleanFunnelParams(props.filters))
                return await api.get('api/action/funnel/?' + urlParams)
            },
        },
    }),
})
