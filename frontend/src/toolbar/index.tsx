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
                console.error('toolbar fetch failed', error, reducerKey, actionKey)
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

win['ph_load_toolbar'] = async function (toolbarParams: ToolbarParams, posthog: PostHog) {
    // If toolbarFlagsKey is present, fetch the feature flags from the backend
    if (toolbarParams.toolbarFlagsKey && toolbarParams.apiURL) {
        try {
            const url = `${toolbarParams.apiURL}/api/user/get_toolbar_preloaded_flags?key=${toolbarParams.toolbarFlagsKey}`

            const response = await fetch(url, {
                credentials: 'include',
            })

            if (response.ok) {
                const data = await response.json()
                if (posthog && data.featureFlags) {
                    posthog.featureFlags.overrideFeatureFlags({ flags: data.featureFlags })
                }
                // Also store in toolbarParams for backward compatibility
                toolbarParams.featureFlags = data.featureFlags
            } else {
                const errorText = await response.text()
                console.error('[Toolbar Flags] Failed to fetch toolbar feature flags:', response.statusText)
                console.error('[Toolbar Flags] Status code:', response.status)
                console.error('[Toolbar Flags] Error response:', errorText)
                console.error('[Toolbar Flags] Request URL:', url)
                console.error('[Toolbar Flags] This likely means:')
                console.error(
                    '[Toolbar Flags]   1. prepare_toolbar_preloaded_flags was not called before launching toolbar'
                )
                console.error('[Toolbar Flags]   2. The cache key expired (5 min TTL)')
                console.error('[Toolbar Flags]   3. The cache key does not match')
            }
        } catch (error) {
            console.error('[Toolbar Flags] Error fetching toolbar feature flags:', error)
        }
    } else {
    }

    initKeaInToolbar()
    const container = document.createElement('div')
    const root = createRoot(container)

    document.body.appendChild(container)

    if (!posthog) {
        console.warn(
            '⚠️⚠️⚠️ Loaded toolbar via old version of posthog-js that does not support feature flags. Please upgrade! ⚠️⚠️⚠️'
        )
    }

    root.render(
        <ToolbarApp
            {...toolbarParams}
            actionId={parseInt(String(toolbarParams.actionId))}
            experimentId={parseInt(String(toolbarParams.experimentId))}
            posthog={posthog}
        />
    )
}

/** @deprecated, use "ph_load_toolbar" instead */
win['ph_load_editor'] = win['ph_load_toolbar']
