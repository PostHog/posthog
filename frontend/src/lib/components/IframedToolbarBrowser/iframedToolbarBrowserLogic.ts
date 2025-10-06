import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'
import { RefObject } from 'react'

import {
    AuthorizedUrlListType,
    authorizedUrlListLogic,
    defaultAuthorizedUrlProperties,
} from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import {
    DEFAULT_HEATMAP_FILTERS,
    PostHogAppToolbarEvent,
    calculateViewportRange,
} from 'lib/components/IframedToolbarBrowser/utils'
import { CommonFilters, HeatmapFixedPositionMode } from 'lib/components/heatmaps/types'
import { LemonBannerProps } from 'lib/lemon-ui/LemonBanner'
import { teamLogic } from 'scenes/teamLogic'

import { ToolbarUserIntent } from '~/types'

import type { iframedToolbarBrowserLogicType } from './iframedToolbarBrowserLogicType'

export type IframedToolbarBrowserLogicProps = {
    iframeRef: RefObject<HTMLIFrameElement | null>
    clearBrowserUrlOnUnmount?: boolean
    userIntent?: ToolbarUserIntent
    automaticallyAuthorizeBrowserUrl?: boolean
}

export interface IFrameBanner {
    level: LemonBannerProps['type']
    message: string | JSX.Element
}

export const UserIntentVerb: {
    [K in ToolbarUserIntent]: string
} = {
    heatmaps: 'view the heatmap',
    'add-action': 'add actions',
    'edit-action': 'edit the action',
    'add-experiment': 'add web experiment',
    'edit-experiment': 'edit the experiment',
}

export const iframedToolbarBrowserLogic = kea<iframedToolbarBrowserLogicType>([
    path(['lib', 'components', 'iframedToolbarBrowser', 'iframedToolbarBrowserLogic']),
    props({
        automaticallyAuthorizeBrowserUrl: false,
    } as IframedToolbarBrowserLogicProps),

    connect(() => ({
        values: [
            authorizedUrlListLogic({ ...defaultAuthorizedUrlProperties, type: AuthorizedUrlListType.TOOLBAR_URLS }),
            ['urlsKeyed', 'checkUrlIsAuthorized'],
            teamLogic,
            ['currentTeam'],
        ],
        actions: [
            authorizedUrlListLogic({ ...defaultAuthorizedUrlProperties, type: AuthorizedUrlListType.TOOLBAR_URLS }),
            ['addUrl'],
            teamLogic,
            ['updateCurrentTeamSuccess'],
        ],
    })),

    actions({
        setBrowserUrl: (url: string | null) => ({ url }),
        setProposedBrowserUrl: (url: string | null) => ({ url }),
        onIframeLoad: true,
        sendToolbarMessage: (type: PostHogAppToolbarEvent, payload?: Record<string, any>) => ({
            type,
            payload,
        }),
        setIframeWidth: (width: number | null) => ({ width }),
        setIframeBanner: (banner: IFrameBanner | null) => ({ banner }),
        startTrackingLoading: true,
        stopTrackingLoading: true,
        enableElementSelector: true,
        disableElementSelector: true,
        setNewActionName: (name: string | null) => ({ name }),
        toolbarMessageReceived: (type: PostHogAppToolbarEvent, payload: Record<string, any>) => ({ type, payload }),
        setCurrentPath: (path: string) => ({ path }),
        setInitialPath: (path: string) => ({ path }),
    }),

    reducers(({ props }) => ({
        // they're called common filters in the toolbar because they're shared between heatmaps and clickmaps
        // the name is continued here since they're passed down into the embedded iframe
        commonFilters: [
            { date_from: '-7d' } as CommonFilters,
            {
                setCommonFilters: (_, { filters }) => filters,
            },
        ],
        heatmapColorPalette: [
            'default' as string | null,
            {
                setHeatmapColorPalette: (_, { Palette }) => Palette,
            },
        ],
        heatmapFilters: [
            DEFAULT_HEATMAP_FILTERS,
            {
                patchHeatmapFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        heatmapFixedPositionMode: [
            'fixed' as HeatmapFixedPositionMode,
            {
                setHeatmapFixedPositionMode: (_, { mode }) => mode,
            },
        ],
        iframeWidth: [
            null as number | null,
            {
                setIframeWidth: (_, { width }) => width,
            },
        ],
        browserUrl: [
            null as string | null,
            { persist: props.userIntent == 'heatmaps' },
            {
                setBrowserUrl: (_, { url }) => url,
            },
        ],
        currentPath: [
            // this does not have the leading / because we always need that to be a given since this value is user-editable
            '' as string,
            {
                setCurrentPath: (_, { path }) => path,
            },
        ],
        initialPath: [
            // similar to currentPath, this also does not have the leading /
            // this is used to set the initial browser URL if the user provides a path to navigate to
            // we can't do this from within the iFrame with window.location.href = currentPath because we get XSS errors
            '' as string,
            {
                setInitialPath: (_, { path }) => path,
            },
        ],
        loading: [
            false as boolean,
            {
                setBrowserUrl: (state, { url }) => (url?.trim().length ? true : state),
                setIframeBanner: (state, { banner }) => (banner?.level == 'error' ? false : state),
                startTrackingLoading: () => true,
                stopTrackingLoading: () => false,
            },
        ],
        iframeBanner: [
            null as IFrameBanner | null,
            {
                setIframeBanner: (_, { banner }) => banner,
            },
        ],
        proposedBrowserUrl: [
            null as string | null,
            {
                setProposedBrowserUrl: (_, { url }) => url,
            },
        ],
    })),

    selectors({
        isBrowserUrlAuthorized: [
            (s) => [s.browserUrl, s.checkUrlIsAuthorized],
            (browserUrl, checkUrlIsAuthorized) => {
                if (!browserUrl) {
                    return false
                }
                return checkUrlIsAuthorized(browserUrl)
            },
        ],
        isProposedBrowserUrlAuthorized: [
            (s) => [s.proposedBrowserUrl, s.checkUrlIsAuthorized],
            (proposedBrowserUrl, checkUrlIsAuthorized) => {
                if (!proposedBrowserUrl) {
                    return false
                }
                return checkUrlIsAuthorized(proposedBrowserUrl)
            },
        ],

        viewportRange: [
            (s) => [s.heatmapFilters, s.iframeWidth],
            (heatmapFilters, iframeWidth) => {
                return iframeWidth ? calculateViewportRange(heatmapFilters, iframeWidth) : { min: 0, max: 1800 }
            },
        ],
        currentFullUrl: [
            (s) => [s.browserUrl, s.currentPath],
            (browserUrl, currentPath) => {
                if (!browserUrl) {
                    return null
                }
                return browserUrl + '/' + currentPath
            },
        ],
    }),

    listeners(({ actions, cache, props, values }) => ({
        sendToolbarMessage: ({ type, payload }) => {
            props.iframeRef?.current?.contentWindow?.postMessage(
                {
                    type,
                    payload,
                },
                '*'
            )
        },
        setProposedBrowserUrl: ({ url }) => {
            if (url) {
                if (props.automaticallyAuthorizeBrowserUrl && !values.isProposedBrowserUrlAuthorized) {
                    actions.addUrl(url)
                } else {
                    actions.setBrowserUrl(url)
                }
            }
        },

        // actions
        enableElementSelector: () => {
            actions.sendToolbarMessage(PostHogAppToolbarEvent.PH_ELEMENT_SELECTOR, { enabled: true })
        },
        disableElementSelector: () => {
            actions.sendToolbarMessage(PostHogAppToolbarEvent.PH_ELEMENT_SELECTOR, { enabled: false })
        },
        setNewActionName: ({ name }) => {
            actions.sendToolbarMessage(PostHogAppToolbarEvent.PH_NEW_ACTION_NAME, { name })
        },

        onIframeLoad: () => {
            // we get this callback whether the iframe loaded successfully or not
            // and don't get a signal if the load was successful, so we have to check
            // but there's no slam dunk way to do that

            const init = (): void => {
                actions.sendToolbarMessage(PostHogAppToolbarEvent.PH_APP_INIT)
            }

            const onIframeMessage = (e: MessageEvent): void => {
                const type: PostHogAppToolbarEvent = e?.data?.type
                const payload = e?.data?.payload

                actions.toolbarMessageReceived(type, payload)

                if (!type || !type.startsWith('ph-')) {
                    return
                }
                if (!values.checkUrlIsAuthorized(e.origin)) {
                    console.warn(
                        'ignoring message from iframe with origin not in authorized toolbar urls',
                        e.origin,
                        e.data
                    )
                    return
                }

                switch (type) {
                    case PostHogAppToolbarEvent.PH_TOOLBAR_INIT:
                        return init()
                    case PostHogAppToolbarEvent.PH_TOOLBAR_READY:
                        if (props.userIntent === 'heatmaps') {
                            posthog.capture('in-app heatmap frame loaded', {
                                inapp_heatmap_page_url_visited: values.browserUrl,
                                inapp_heatmap_filters: values.heatmapFilters,
                                inapp_heatmap_color_palette: values.heatmapColorPalette,
                                inapp_heatmap_fixed_position_mode: values.heatmapFixedPositionMode,
                            })
                            // reset loading tracking - if we're e.g. slow this will avoid a flash of warning message
                            return actions.startTrackingLoading()
                        }
                        return
                    case PostHogAppToolbarEvent.PH_NEW_ACTION_CREATED:
                        actions.setNewActionName(null)
                        actions.disableElementSelector()
                        return
                    case PostHogAppToolbarEvent.PH_TOOLBAR_NAVIGATED:
                        // remove leading / from path
                        return actions.setCurrentPath(payload.path.replace(/^\/+/, ''))
                    default:
                        console.warn(`[PostHog Heatmaps] Received unknown child window message: ${type}`)
                }
            }

            window.addEventListener('message', onIframeMessage, false)
            // We call init in case the toolbar got there first (unlikely)
            init()
        },

        setBrowserUrl: ({ url }) => {
            if (url?.trim().length) {
                actions.startTrackingLoading()
            }
        },
        startTrackingLoading: () => {
            actions.setIframeBanner(null)

            clearTimeout(cache.errorTimeout)
            cache.errorTimeout = setTimeout(() => {
                actions.setIframeBanner({ level: 'error', message: 'The heatmap failed to load (or is very slow).' })
            }, 7500)

            clearTimeout(cache.warnTimeout)
            cache.warnTimeout = setTimeout(() => {
                actions.setIframeBanner({ level: 'warning', message: 'Still waiting for the toolbar to load.' })
            }, 3000)
        },

        stopTrackingLoading: () => {
            actions.setIframeBanner(null)

            clearTimeout(cache.errorTimeout)
            clearTimeout(cache.warnTimeout)
        },
        setIframeBanner: ({ banner }) => {
            posthog.capture('in-app iFrame banner set', {
                level: banner?.level,
                message: banner?.message,
            })
        },
        updateCurrentTeamSuccess: () => {
            if (
                props.automaticallyAuthorizeBrowserUrl &&
                values.proposedBrowserUrl &&
                values.currentTeam?.app_urls?.includes(values.proposedBrowserUrl)
            ) {
                actions.setBrowserUrl(values.proposedBrowserUrl)
                actions.setProposedBrowserUrl(null)
            }
        },
    })),

    afterMount(({ actions, values }) => {
        if (values.browserUrl?.trim().length) {
            actions.startTrackingLoading()
        }
    }),
    beforeUnmount(({ actions, props, cache }) => {
        props.clearBrowserUrlOnUnmount && actions.setBrowserUrl('')

        // Clean up loading timeouts to prevent memory leaks and ghost banner messages
        if (cache.errorTimeout) {
            clearTimeout(cache.errorTimeout)
        }
        if (cache.warnTimeout) {
            clearTimeout(cache.warnTimeout)
        }
    }),
])
