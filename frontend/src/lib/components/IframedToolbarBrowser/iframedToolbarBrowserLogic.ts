import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { authorizedUrlListLogic, AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { CommonFilters, HeatmapFilters, HeatmapFixedPositionMode } from 'lib/components/heatmaps/types'
import {
    calculateViewportRange,
    DEFAULT_HEATMAP_FILTERS,
    PostHogAppToolbarEvent,
} from 'lib/components/IframedToolbarBrowser/utils'
import { LemonBannerProps } from 'lib/lemon-ui/LemonBanner'
import posthog from 'posthog-js'
import { RefObject } from 'react'

import type { iframedToolbarBrowserLogicType } from './iframedToolbarBrowserLogicType'

export type IframedToolbarBrowserLogicProps = {
    iframeRef: RefObject<HTMLIFrameElement | null>
    clearBrowserUrlOnUnmount?: boolean
}

export interface IFrameBanner {
    level: LemonBannerProps['type']
    message: string | JSX.Element
}

export const iframedToolbarBrowserLogic = kea<iframedToolbarBrowserLogicType>([
    path(['lib', 'components', 'iframedToolbarBrowser', 'iframedToolbarBrowserLogic']),
    props({} as IframedToolbarBrowserLogicProps),

    connect({
        values: [
            authorizedUrlListLogic({ actionId: null, type: AuthorizedUrlListType.TOOLBAR_URLS }),
            ['urlsKeyed', 'checkUrlIsAuthorized'],
        ],
    }),

    actions({
        setBrowserUrl: (url: string | null) => ({ url }),
        onIframeLoad: true,
        sendToolbarMessage: (type: PostHogAppToolbarEvent, payload?: Record<string, any>) => ({
            type,
            payload,
        }),
        // TRICKY: duplicated with the heatmapLogic so that we can share the settings picker
        patchHeatmapFilters: (filters: Partial<HeatmapFilters>) => ({ filters }),
        setHeatmapColorPalette: (Palette: string | null) => ({ Palette }),
        setHeatmapFixedPositionMode: (mode: HeatmapFixedPositionMode) => ({ mode }),
        setCommonFilters: (filters: CommonFilters) => ({ filters }),
        // TRICKY: duplication ends
        setIframeWidth: (width: number | null) => ({ width }),
        setIframeBanner: (banner: IFrameBanner | null) => ({ banner }),
        startTrackingLoading: true,
        stopTrackingLoading: true,
    }),

    reducers({
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
            { persist: true },
            {
                setBrowserUrl: (_, { url }) => url,
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
    }),

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

        viewportRange: [
            (s) => [s.heatmapFilters, s.iframeWidth],
            (heatmapFilters, iframeWidth) => {
                return iframeWidth ? calculateViewportRange(heatmapFilters, iframeWidth) : { min: 0, max: 1800 }
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

        patchHeatmapFilters: ({ filters }) => {
            actions.sendToolbarMessage(PostHogAppToolbarEvent.PH_PATCH_HEATMAP_FILTERS, { filters })
        },

        setHeatmapFixedPositionMode: ({ mode }) => {
            actions.sendToolbarMessage(PostHogAppToolbarEvent.PH_HEATMAPS_FIXED_POSITION_MODE, {
                fixedPositionMode: mode,
            })
        },

        setHeatmapColorPalette: ({ Palette }) => {
            actions.sendToolbarMessage(PostHogAppToolbarEvent.PH_HEATMAPS_COLOR_PALETTE, {
                colorPalette: Palette,
            })
        },

        setCommonFilters: ({ filters }) => {
            actions.sendToolbarMessage(PostHogAppToolbarEvent.PH_HEATMAPS_COMMON_FILTERS, { commonFilters: filters })
        },

        onIframeLoad: () => {
            // we get this callback whether the iframe loaded successfully or not
            // and don't get a signal if the load was successful, so we have to check
            // but there's no slam dunk way to do that

            const init = (): void => {
                actions.sendToolbarMessage(PostHogAppToolbarEvent.PH_APP_INIT, {
                    filters: values.heatmapFilters,
                    colorPalette: values.heatmapColorPalette,
                    fixedPositionMode: values.heatmapFixedPositionMode,
                    commonFilters: values.commonFilters,
                })
                actions.sendToolbarMessage(PostHogAppToolbarEvent.PH_HEATMAPS_CONFIG, {
                    enabled: true,
                })
            }

            const onIframeMessage = (e: MessageEvent): void => {
                const type: PostHogAppToolbarEvent = e?.data?.type

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
                        posthog.capture('in-app heatmap frame loaded', {
                            inapp_heatmap_page_url_visited: values.browserUrl,
                            inapp_heatmap_filters: values.heatmapFilters,
                            inapp_heatmap_color_palette: values.heatmapColorPalette,
                            inapp_heatmap_fixed_position_mode: values.heatmapFixedPositionMode,
                        })
                        // reset loading tracking - if we're e.g. slow this will avoid a flash of warning message
                        return actions.startTrackingLoading()
                    case PostHogAppToolbarEvent.PH_TOOLBAR_HEATMAP_LOADING:
                        return actions.startTrackingLoading()
                    case PostHogAppToolbarEvent.PH_TOOLBAR_HEATMAP_LOADED:
                        posthog.capture('in-app heatmap loaded', {
                            inapp_heatmap_page_url_visited: values.browserUrl,
                            inapp_heatmap_filters: values.heatmapFilters,
                            inapp_heatmap_color_palette: values.heatmapColorPalette,
                            inapp_heatmap_fixed_position_mode: values.heatmapFixedPositionMode,
                        })
                        return actions.stopTrackingLoading()
                    case PostHogAppToolbarEvent.PH_TOOLBAR_HEATMAP_FAILED:
                        posthog.capture('in-app heatmap failed', {
                            inapp_heatmap_page_url_visited: values.browserUrl,
                            inapp_heatmap_filters: values.heatmapFilters,
                            inapp_heatmap_color_palette: values.heatmapColorPalette,
                            inapp_heatmap_fixed_position_mode: values.heatmapFixedPositionMode,
                        })
                        actions.stopTrackingLoading()
                        actions.setIframeBanner({ level: 'error', message: 'The heatmap failed to load.' })
                        return
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
    })),

    afterMount(({ actions, values }) => {
        if (values.browserUrl?.trim().length) {
            actions.startTrackingLoading()
        }
    }),
    beforeUnmount(({ actions, props }) => {
        props.clearBrowserUrlOnUnmount && actions.setBrowserUrl('')
    }),
])
