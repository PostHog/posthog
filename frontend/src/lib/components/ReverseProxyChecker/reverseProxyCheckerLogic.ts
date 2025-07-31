import { kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { ActivationTask } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { activationLogic } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { hogql } from '~/queries/utils'

import type { reverseProxyCheckerLogicType } from './reverseProxyCheckerLogicType'

const CHECK_INTERVAL_MS = 1000 * 60 * 60 // 1 hour

export const reverseProxyCheckerLogic = kea<reverseProxyCheckerLogicType>([
    path(['components', 'ReverseProxyChecker', 'reverseProxyCheckerLogic']),
    loaders(({ values, cache }) => ({
        hasReverseProxy: [
            false as boolean | null,
            {
                loadHasReverseProxy: async () => {
                    if (cache.lastCheckedTimestamp > Date.now() - CHECK_INTERVAL_MS) {
                        return values.hasReverseProxy
                    }

                    cache.lastCheckedTimestamp = Date.now()

                    const query = hogql`
                        SELECT DISTINCT properties.$lib_custom_api_host AS lib_custom_api_host
                        FROM events
                        WHERE timestamp >= now() - INTERVAL 1 DAY 
                        AND timestamp <= now()
                        AND properties.$lib_custom_api_host IS NOT NULL
                        AND event IN ('$pageview', '$screen')
                        LIMIT 10`

                    const res = await api.queryHogQL(query)
                    return !!res.results?.find((x) => !!x[0])
                },
            },
        ],
    })),
    listeners(({ values }) => ({
        loadHasReverseProxySuccess: () => {
            if (values.hasReverseProxy) {
                activationLogic.findMounted()?.actions.markTaskAsCompleted(ActivationTask.SetUpReverseProxy)
            }
        },
    })),
])
