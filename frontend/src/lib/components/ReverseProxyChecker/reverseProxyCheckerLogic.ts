import { afterMount, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { sceneLogic } from 'scenes/sceneLogic'

import { hogql } from '~/queries/utils'

import type { reverseProxyCheckerLogicType } from './reverseProxyCheckerLogicType'

const CHECK_INTERVAL_MS = 1000 * 60 * 10 // 10 minutes

export const reverseProxyCheckerLogic = kea<reverseProxyCheckerLogicType>([
    path(['components', 'ReverseProxyChecker', 'reverseProxyCheckerLogic']),
    loaders(({ values, cache }) => ({
        hasReverseProxy: [
            // null until the detection query resolves — consumers must distinguish "not yet
            // checked" from a confirmed `false` so they don't act before the result is in.
            null as boolean | null,
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

                    const currentScene = sceneLogic.findMounted()?.values.activeSceneId ?? 'Onboarding'
                    try {
                        const res = await api.queryHogQL(query, {
                            scene: currentScene,
                            productKey: 'platform_and_support',
                        })
                        return !!res.results?.find((x) => !!x[0])
                    } catch (error) {
                        // This check is advisory (used only to auto-complete a setup task).
                        // Swallow errors so kea-loaders does not surface a user-visible toast
                        // on every scene that mounts ProductSetupButton.
                        //
                        // Capturing the original `error` directly (rather than wrapping it
                        // in `new Error('...', { cause })`) keeps the error type at the top
                        // of `$exception_list`, so the central `before_send` filter in
                        // `selfReadOnlyModeLogic` can drop `ReadOnlyModeError` without
                        // assuming posthog-js serialises the cause chain.
                        posthog.captureException(error, {
                            posthog_source: 'reverseProxyCheckerLogic.loadHasReverseProxy',
                        })
                        return values.hasReverseProxy
                    }
                },
            },
        ],
    })),
    listeners(({ values }) => ({
        loadHasReverseProxySuccess: () => {
            if (values.hasReverseProxy) {
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.SetUpReverseProxy)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadHasReverseProxy()
    }),
])
