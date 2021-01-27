import { kea } from 'kea'
import { insightLogic, ViewType } from 'scenes/insights/insightLogic'
import { cleanFunnelParams } from './funnelLogic'
import { pollFunnel } from './funnelLogic'

export const funnelVizLogic = kea({
    key: (props) => props.dashboardItemId || 'some_funnel',
    loaders: ({ props }) => ({
        results: {
            __default: [],
            loadResults: async (refresh = false) => {
                if (!refresh && props.cachedResults) {
                    return props.cachedResults
                }
                const { from_dashboard } = props.filters
                const cleanedParams = cleanFunnelParams(props.filters)
                const params = {
                    ...(refresh ? { refresh: true } : {}),
                    ...(from_dashboard ? { from_dashboard } : {}),
                    ...cleanedParams,
                }
                let result

                insightLogic.actions.startQuery()
                try {
                    result = await pollFunnel(params)
                } catch (e) {
                    insightLogic.actions.endQuery(ViewType.FUNNELS, e)
                    return []
                }
                insightLogic.actions.endQuery(ViewType.FUNNELS)
                return result
            },
        },
    }),
})
