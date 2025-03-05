import { afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { ActivationTask } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { activationLogic } from '~/layout/navigation-3000/sidepanel/panels/activation/activationLogic'
import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'

import type { reverseProxyCheckerLogicType } from './reverseProxyCheckerLogicType'

const CHECK_INTERVAL_MS = 1000 * 60 * 60 // 1 hour

export const reverseProxyCheckerLogic = kea<reverseProxyCheckerLogicType>([
    path(['components', 'ReverseProxyChecker', 'reverseProxyCheckerLogic']),
    loaders({
        hasReverseProxy: [
            false as boolean | null,
            {
                loadHasReverseProxy: async () => {
                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: hogql`SELECT properties.$lib_custom_api_host AS lib_custom_api_host
                                FROM events
                                WHERE timestamp >= now() - INTERVAL 1 DAY 
                                AND timestamp <= now()
                                ORDER BY timestamp DESC
                                limit 10`,
                    }

                    const res = await api.query(query)
                    return !!res.results?.find((x) => !!x[0])
                },
            },
        ],
    }),
    listeners(({ values }) => ({
        loadHasReverseProxySuccess: () => {
            if (values.hasReverseProxy) {
                activationLogic.findMounted()?.actions.markTaskAsCompleted(ActivationTask.SetUpReverseProxy)
            }
        },
    })),
    reducers({
        lastCheckedTimestamp: [
            0,
            { persist: true },
            {
                loadHasReverseProxySuccess: () => Date.now(),
            },
        ],
    }),
    afterMount(({ actions, values }) => {
        if (values.lastCheckedTimestamp < Date.now() - CHECK_INTERVAL_MS) {
            actions.loadHasReverseProxy()
        }
    }),
])
