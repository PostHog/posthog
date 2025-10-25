import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'
import { RefObject } from 'react'

import api from 'lib/api'
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
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { CommonFilters, HeatmapFilters, HeatmapFixedPositionMode } from 'lib/components/heatmaps/types'
import { LemonBannerProps } from 'lib/lemon-ui/LemonBanner'
import { objectsEqual } from 'lib/utils'
import { removeReplayIframeDataFromLocalStorage } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { hogql } from '~/queries/utils'

import type { heatmapsBrowserLogicType } from './heatmapsBrowserLogicType'

export type HeatmapsBrowserLogicProps = {
    iframeRef: RefObject<HTMLIFrameElement | null>
}

export interface IFrameBanner {
    level: LemonBannerProps['type']
    message: string | JSX.Element
}

export interface ReplayIframeData {
    html: string
    width: number // NB this should be meta width
    height: number // NB this should be meta height
    startDateTime: string | undefined
    url: string | undefined
}

// Helper function to detect if a URL contains regex pattern characters
const isUrlPattern = (url: string): boolean => {
    return /[*+?^${}()|[\]\\]/.test(url)
}

const normalizeUrlPath = (urlObj: URL): string => {
    if (urlObj.pathname === '') {
        urlObj.pathname = '/'
    }
    return urlObj.toString()
}

export const heatmapsBrowserLogic = kea<heatmapsBrowserLogicType>([
    path(['scenes', 'heatmaps', 'components', 'heatmapsBrowserLogic']),
    props({} as HeatmapsBrowserLogicProps),

    connect(() => ({
        values: [
            authorizedUrlListLogic({
                ...defaultAuthorizedUrlProperties,
                type: AuthorizedUrlListType.TOOLBAR_URLS,
            }),
            ['urlsKeyed', 'checkUrlIsAuthorized'],
            heatmapDataLogic({ context: 'in-app' }),
            ['heatmapEmpty', 'hrefMatchType'],
        ],
        actions: [heatmapDataLogic({ context: 'in-app' }), ['loadHeatmap', 'setHref', 'setHrefMatchType']],
    })),

    actions({
        setBrowserSearch: (searchTerm: string) => ({ searchTerm }),
        setDataUrl: (url: string | null) => ({ url }),
        setDisplayUrl: (url: string | null) => ({ url }),
        onIframeLoad: true,
        sendToolbarMessage: (type: PostHogAppToolbarEvent, payload?: Record<string, any>) => ({
            type,
            payload,
        }),
        loadTopUrls: true,
        maybeLoadTopUrls: true,
        loadBrowserSearchResults: true,
        // TRICKY: duplicated with the heatmapLogic so that we can share the settings picker
        patchHeatmapFilters: (filters: Partial<HeatmapFilters>) => ({ filters }),
        setHeatmapColorPalette: (Palette: string | null) => ({ Palette }),
        setHeatmapFixedPositionMode: (mode: HeatmapFixedPositionMode) => ({ mode }),
        setCommonFilters: (filters: CommonFilters) => ({ filters }),
        // TRICKY: duplication ends
        setIframeWidth: (width: number | null) => ({ width }),
        toggleFilterPanelCollapsed: true,
        setIframeBanner: (banner: IFrameBanner | null) => ({ banner }),
        startTrackingLoading: true,
        stopTrackingLoading: true,
        setReplayIframeData: (replayIframeData: ReplayIframeData | null) => ({ replayIframeData }),
        setReplayIframeDataURL: (url: string | null) => ({ url }),
    }),

    loaders(({ values }) => ({
        browserSearchResults: [
            null as string[] | null,
            {
                loadBrowserSearchResults: async () => {
                    if (!values.browserSearchTerm) {
                        return []
                    }

                    const query = hogql`
                        SELECT distinct properties.$current_url AS urls
                        FROM events
                        WHERE timestamp >= now() - INTERVAL 7 DAY
                        AND timestamp <= now()
                        AND properties.$current_url like '%${hogql.identifier(values.browserSearchTerm)}%'
                        ORDER BY timestamp DESC
                        LIMIT 100`

                    const res = await api.queryHogQL(query)

                    return res.results?.map((x) => x[0]) as string[]
                },
            },
        ],

        topUrls: [
            null as { url: string; count: number }[] | null,
            {
                loadTopUrls: async () => {
                    const query = hogql`
                        SELECT properties.$current_url AS url, count() as count
                        FROM events
                        WHERE timestamp >= now() - INTERVAL 7 DAY
                        AND event in ('$pageview', '$autocapture')
                        AND timestamp <= now()
                        GROUP BY properties.$current_url
                        ORDER BY count DESC
                        LIMIT 10`

                    const res = await api.queryHogQL(query)

                    return res.results?.map((x) => ({ url: x[0], count: x[1] })) as { url: string; count: number }[]
                },
            },
        ],
    })),

    reducers({
        hasValidReplayIframeData: [
            false,
            {
                setReplayIframeData: (_, { replayIframeData }) =>
                    !!replayIframeData?.url?.trim().length && !!replayIframeData?.html.trim().length,
            },
        ],
        replayIframeData: [
            null as ReplayIframeData | null,
            {
                setReplayIframeData: (_, { replayIframeData }) => replayIframeData,
                setReplayIframeDataURL: (state, { url }) => {
                    if (state === null) {
                        return null
                    }
                    return { ...state, url } as ReplayIframeData
                },
            },
        ],
        filterPanelCollapsed: [
            false as boolean,
            { persist: true },
            {
                toggleFilterPanelCollapsed: (state) => !state,
            },
        ],
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
        browserSearchTerm: [
            '',
            {
                setBrowserSearch: (_, { searchTerm }) => searchTerm,
            },
        ],
        dataUrl: [
            null as string | null,
            {
                setDataUrl: (_, { url }) => url,
            },
        ],
        loading: [
            false as boolean,
            {
                setDataUrl: (state, { url }) => (url?.trim().length ? true : state),
                setDisplayUrl: (state, { url }) => (url?.trim().length ? true : state),
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
        widthOverride: [
            1024 as number | null,
            {
                setIframeWidth: (_, { width }) => width,
            },
        ],
        displayUrl: [
            null as string | null,
            {
                setDisplayUrl: (_, { url }) => url,
            },
        ],
    }),

    selectors({
        browserUrlSearchOptions: [
            (s) => [s.browserSearchResults, s.topUrls, s.browserSearchTerm],
            (browserSearchResults, topUrls, browserSearchTerm) => {
                return browserSearchTerm ? browserSearchResults : (topUrls?.map((x) => x.url) ?? [])
            },
        ],

        isBrowserUrlAuthorized: [
            (s) => [s.dataUrl, s.checkUrlIsAuthorized],
            (dataUrl, checkUrlIsAuthorized) => {
                if (!dataUrl) {
                    return false
                }
                return checkUrlIsAuthorized(dataUrl)
            },
        ],
        isBrowserUrlValid: [
            (s) => [s.dataUrl],
            (dataUrl) => {
                if (!dataUrl) {
                    // an empty dataUrl is valid
                    // since we just won't do anything with it
                    return true
                }

                try {
                    // must be something that can be parsed as a URL
                    new URL(dataUrl)
                    // and must be a valid URL that our redirects can cope with
                    // this is a very loose check, but `http:/blaj` is not valid for PostHog
                    // but survives new URL(http:/blaj)
                    return dataUrl.includes('://')
                } catch {
                    return false
                }
            },
        ],

        viewportRange: [
            (s) => [s.heatmapFilters, s.iframeWidth],
            (heatmapFilters, iframeWidth) => {
                return iframeWidth ? calculateViewportRange(heatmapFilters, iframeWidth) : { min: 0, max: 1800 }
            },
        ],

        noPageviews: [
            (s) => [s.topUrlsLoading, s.topUrls],
            (topUrlsLoading, topUrls) => !topUrlsLoading && (!topUrls || topUrls.length === 0),
        ],
    }),

    listeners(({ actions, props, values, cache }) => ({
        setDisplayUrl: ({ url }) => {
            actions.setDataUrl(url?.trim() ?? null)
        },
        setReplayIframeData: ({ replayIframeData }) => {
            if (replayIframeData && replayIframeData.url) {
                actions.setHref(replayIframeData.url)
                // Auto-detect match type for replay data URLs too
                const isPattern = isUrlPattern(replayIframeData.url)
                actions.setHrefMatchType(isPattern ? 'pattern' : 'exact')
            } else {
                removeReplayIframeDataFromLocalStorage()
            }
        },

        setBrowserSearch: async ({ searchTerm }, breakpoint) => {
            await breakpoint(200)
            actions.loadBrowserSearchResults()

            // Also update match type based on search term if it has regex patterns
            if (searchTerm && isUrlPattern(searchTerm)) {
                actions.setHrefMatchType('pattern')
                actions.setHref(searchTerm)
            }
        },

        sendToolbarMessage: ({ type, payload }) => {
            props.iframeRef?.current?.contentWindow?.postMessage(
                {
                    type,
                    payload,
                },
                '*'
            )
        },

        onIframeLoad: () => {
            // it should be impossible to load an iframe without a dataUrl
            // right?!
            const url = values.dataUrl ?? ''
            actions.setHref(url)

            // Ensure match type is set correctly when iframe loads
            const isPattern = isUrlPattern(url)
            actions.setHrefMatchType(isPattern ? 'pattern' : 'exact')

            actions.loadHeatmap()
            posthog.capture('in-app heatmap iframe loaded', {
                inapp_heatmap_page_url_visited: values.dataUrl,
                inapp_heatmap_filters: values.heatmapFilters,
                inapp_heatmap_color_palette: values.heatmapColorPalette,
                inapp_heatmap_fixed_position_mode: values.heatmapFixedPositionMode,
            })
        },

        maybeLoadTopUrls: () => {
            if (!values.topUrls && !values.topUrlsLoading) {
                actions.loadTopUrls()
            }
        },

        setReplayIframeDataURL: async ({ url }, breakpoint) => {
            await breakpoint(150)
            if (url?.trim().length) {
                actions.setHref(url)
                // Auto-detect match type for replay URLs too
                const isPattern = isUrlPattern(url)
                actions.setHrefMatchType(isPattern ? 'pattern' : 'exact')
            }
        },

        setDataUrl: ({ url }) => {
            actions.maybeLoadTopUrls()
            if (url?.trim().length) {
                actions.startTrackingLoading()

                let normalizedUrl = url.trim()

                const isPattern = isUrlPattern(normalizedUrl)
                if (!isPattern) {
                    const urlObj = new URL(normalizedUrl)
                    normalizedUrl = normalizeUrlPath(urlObj)
                }

                actions.setHref(normalizedUrl)
                actions.setHrefMatchType(isPattern ? 'pattern' : 'exact')
            }
        },

        startTrackingLoading: () => {
            actions.setIframeBanner(null)

            cache.disposables.add(() => {
                const timerId = setTimeout(() => {
                    actions.setIframeBanner({
                        level: 'error',
                        message: 'The heatmap failed to load (or is very slow).',
                    })
                }, 7500)
                return () => clearTimeout(timerId)
            }, 'errorTimeout')
        },

        stopTrackingLoading: () => {
            actions.setIframeBanner(null)

            // Clear timeouts using disposables
            cache.disposables.dispose('errorTimeout')
            cache.disposables.dispose('warnTimeout')
        },
    })),

    afterMount(({ actions, values }) => {
        if (values.dataUrl?.trim().length && values.displayUrl?.trim().length) {
            actions.startTrackingLoading()
        } else {
            actions.maybeLoadTopUrls()
        }
    }),

    urlToAction(({ actions, values }) => ({
        '/heatmaps': (_, searchParams) => {
            if (searchParams.pageURL && searchParams.pageURL !== values.displayUrl) {
                actions.setDisplayUrl(searchParams.pageURL)
            }
            if (searchParams.dataUrl && searchParams.dataUrl !== values.dataUrl) {
                actions.setDataUrl(searchParams.dataUrl)
            }
            if (searchParams.heatmapFilters && !objectsEqual(searchParams.heatmapFilters, values.heatmapFilters)) {
                actions.patchHeatmapFilters(searchParams.heatmapFilters)
            }
            if (searchParams.heatmapPalette && searchParams.heatmapPalette !== values.heatmapColorPalette) {
                actions.setHeatmapColorPalette(searchParams.heatmapPalette)
            }
            if (
                searchParams.heatmapFixedPositionMode &&
                searchParams.heatmapFixedPositionMode !== values.heatmapFixedPositionMode
            ) {
                actions.setHeatmapFixedPositionMode(searchParams.heatmapFixedPositionMode as HeatmapFixedPositionMode)
            }
            if (searchParams.commonFilters && !objectsEqual(searchParams.commonFilters, values.commonFilters)) {
                actions.setCommonFilters(searchParams.commonFilters as CommonFilters)
            }
        },
        '/heatmaps/recording': (_, searchParams) => {
            if (searchParams.iframeStorage) {
                const replayFrameData = JSON.parse(
                    localStorage.getItem(searchParams.iframeStorage) || '{}'
                ) as ReplayIframeData
                actions.setReplayIframeData(replayFrameData)
            }
        },
    })),

    actionToUrl(({ values }) => ({
        setDisplayUrl: ({ url }) => {
            const searchParams = { ...router.values.searchParams, pageURL: url }
            if (!url || url.trim() === '') {
                delete searchParams.pageURL
            }
            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        },
        setDataUrl: ({ url }) => {
            const searchParams = { ...router.values.searchParams, dataUrl: url }
            if (!url || url.trim() === '') {
                delete searchParams.dataUrl
            }
            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        },
        patchHeatmapFilters: () => {
            const searchParams = { ...router.values.searchParams, heatmapFilters: values.heatmapFilters }
            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        },
        setHeatmapColorPalette: ({ Palette }) => {
            const searchParams = { ...router.values.searchParams, heatmapPalette: Palette }
            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        },
        setHeatmapFixedPositionMode: ({ mode }) => {
            const searchParams = { ...router.values.searchParams, heatmapFixedPositionMode: mode }
            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        },
        setCommonFilters: ({ filters }) => {
            const searchParams = { ...router.values.searchParams, commonFilters: filters }
            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        },
    })),

    beforeUnmount(() => {
        // Disposables handle cleanup automatically
    }),
])
