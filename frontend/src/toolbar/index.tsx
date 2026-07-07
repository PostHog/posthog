import '~/styles'
import './styles.scss'

import { KeaPlugin, resetContext } from 'kea'
import { formsPlugin } from 'kea-forms'
import { loadersPlugin } from 'kea-loaders'
import { localStoragePlugin } from 'kea-localstorage'
import { routerPlugin } from 'kea-router'
import { subscriptionsPlugin } from 'kea-subscriptions'
import { waitForPlugin } from 'kea-waitfor'
import { windowValuesPlugin } from 'kea-window-values'
import type { PostHog } from 'posthog-js'
import { createRoot } from 'react-dom/client'

import { disposablesPlugin } from '~/kea-disposables'
import { ToolbarApp } from '~/toolbar/ToolbarApp'
import { canonicalizeApiHost } from '~/toolbar/toolbarConfigLogic'
import { posthogToolbarController, setToolbarRefs } from '~/toolbar/toolbarController'
import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { captureToolbarException } from '~/toolbar/toolbarPosthogJS'
import { safeOverrideFeatureFlags } from '~/toolbar/utils'
import { ToolbarParams } from '~/types'

interface InitKeaProps {
    state?: Record<string, any>
    routerHistory?: any
    routerLocation?: any
    beforePlugins?: KeaPlugin[]
}

const initKeaInToolbar = ({ routerHistory, routerLocation, beforePlugins }: InitKeaProps = {}): void => {
    const plugins = [
        ...(beforePlugins || []),
        disposablesPlugin,
        localStoragePlugin(),
        windowValuesPlugin({ window: window }),
        routerPlugin({
            history: routerHistory,
            location: routerLocation,
            urlPatternOptions: {
                // :TRICKY: What chars to allow in named segment values i.e. ":key"
                // in "/url/:key". Default: "a-zA-Z0-9-_~ %".
                segmentValueCharset: "a-zA-Z0-9-_~ %.@()!'|",
            },
        }),
        formsPlugin,
        loadersPlugin({
            onFailure({ error, reducerKey, actionKey }: { error: any; reducerKey: string; actionKey: string }) {
                toolbarLogger.error('kea_loader', 'Toolbar fetch failed', {
                    reducer_key: reducerKey,
                    action_key: actionKey,
                })
                captureToolbarException(error, 'kea_loader', {
                    reducer_key: reducerKey,
                    action_key: actionKey,
                })
            },
        }),
        subscriptionsPlugin,
        waitForPlugin,
    ]

    resetContext({
        plugins: plugins,
        createStore: {
            compose: (...funcs: any[]) => {
                if (funcs.length === 0) {
                    return <T,>(arg: T) => arg
                }
                if (funcs.length === 1) {
                    return funcs[0]
                }
                return funcs.reduce(
                    (a, b) =>
                        (...args: any) =>
                            a(b(...args))
                )
            },
        },
    })
}

const win = window as any
win['posthogToolbarController'] = posthogToolbarController

win['ph_load_toolbar'] = async function (toolbarParams: ToolbarParams, posthog?: PostHog) {
    // Store the start time so we can measure total load duration in initInstrumentation
    ;(window as any).__posthog_toolbar_load_start = performance.now()

    // If posthog and toolbarFlagsKey is present, fetch the feature flags from the backend
    if (posthog && toolbarParams.toolbarFlagsKey) {
        // Validate with canonicalizeApiHost so an attacker-controlled apiURL in
        // the hash can't receive the credentialed request (the flags key is
        // low-impact on its own, but `credentials: 'include'` would send any
        // cookies for the attacker's origin alongside it).
        const trimmedHost =
            canonicalizeApiHost(posthog.config?.api_host) ||
            canonicalizeApiHost(toolbarParams.apiURL) ||
            window.location.origin
        const flagsUrl = `${trimmedHost}/api/user/get_toolbar_preloaded_flags?key=${toolbarParams.toolbarFlagsKey}`

        // Only the network call is wrapped here: `fetch` rejects solely on transient
        // network-level failures (aborted request, ad blocker / browser extension,
        // connectivity loss, CORS). The flags preload is best-effort and the toolbar
        // degrades cleanly without it, so these are logged rather than surfaced as
        // error-tracking exceptions. Parsing/applying the response is handled separately
        // below so genuine bugs there still get captured.
        let response: Response | undefined
        try {
            response = await fetch(flagsUrl, { credentials: 'include' })
        } catch (error) {
            toolbarLogger.warn('flags', 'Error fetching toolbar feature flags', {
                error: error instanceof Error ? error.message : String(error),
            })
        }

        if (response) {
            try {
                const data = await response.json()
                if (data.featureFlags) {
                    safeOverrideFeatureFlags(posthog, { flags: data.featureFlags })
                } else {
                    toolbarLogger.error('flags', 'Feature flags not found', { response: data })
                    captureToolbarException(
                        new Error(`Toolbar feature flags not found: ${JSON.stringify(data)}`),
                        'preloaded_flags'
                    )
                }
            } catch (error) {
                toolbarLogger.error('flags', 'Error processing toolbar feature flags')
                captureToolbarException(error, 'preloaded_flags_fetch')
            }
        }
    }

    initKeaInToolbar()
    const container = document.createElement('div')
    const root = createRoot(container)

    document.body.appendChild(container)

    if (!posthog) {
        toolbarLogger.warn('init', 'Loaded toolbar via old version of posthog-js that does not support feature flags')
    }

    root.render(
        <ToolbarApp
            {...toolbarParams}
            actionId={parseInt(String(toolbarParams.actionId))}
            experimentId={parseInt(String(toolbarParams.experimentId))}
            posthog={posthog}
        />
    )

    setToolbarRefs(root, container)
}

/** @deprecated, use "ph_load_toolbar" instead */
win['ph_load_editor'] = win['ph_load_toolbar']
