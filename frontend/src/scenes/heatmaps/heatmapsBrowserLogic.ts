import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import {
    authorizedUrlListLogic,
    AuthorizedUrlListType,
    defaultAuthorizedUrlProperties,
} from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { CommonFilters, HeatmapFilters, HeatmapFixedPositionMode } from 'lib/components/heatmaps/types'
import {
    calculateViewportRange,
    DEFAULT_HEATMAP_FILTERS,
    PostHogAppToolbarEvent,
} from 'lib/components/IframedToolbarBrowser/utils'
import { LemonBannerProps } from 'lib/lemon-ui/LemonBanner'
import { objectsEqual } from 'lib/utils'
import posthog from 'posthog-js'
import { RefObject } from 'react'
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

// team id is always available on window
const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id

export const heatmapsBrowserLogic = kea<heatmapsBrowserLogicType>([
    path(['scenes', 'heatmaps', 'heatmapsBrowserLogic']),
    props({} as HeatmapsBrowserLogicProps),

    connect(() => ({
        values: [
            authorizedUrlListLogic({
                ...defaultAuthorizedUrlProperties,
                type: AuthorizedUrlListType.TOOLBAR_URLS,
            }),
            ['urlsKeyed', 'checkUrlIsAuthorized'],
            heatmapDataLogic({ context: 'in-app' }),
            ['heatmapEmpty'],
        ],
        actions: [heatmapDataLogic({ context: 'in-app' }), ['loadHeatmap', 'setHref', 'setHrefMatchType']],
    })),

    actions({
        setBrowserSearch: (searchTerm: string) => ({ searchTerm }),
        setBrowserUrl: (url: string | null) => ({ url }),
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
        browserUrl: [
            null as string | null,
            { persist: true, prefix: `${teamId}__` },
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
        widthOverride: [
            null as number | null,
            {
                setIframeWidth: (_, { width }) => width,
            },
        ],
    }),

    selectors({
        browserUrlSearchOptions: [
            (s) => [s.browserSearchResults, s.topUrls, s.browserSearchTerm],
            (browserSearchResults, topUrls, browserSearchTerm) => {
                return browserSearchTerm ? browserSearchResults : topUrls?.map((x) => x.url) ?? []
            },
        ],

        isBrowserUrlAuthorized: [
            (s) => [s.browserUrl, s.checkUrlIsAuthorized],
            (browserUrl, checkUrlIsAuthorized) => {
                if (!browserUrl) {
                    return false
                }
                return checkUrlIsAuthorized(browserUrl)
            },
        ],
        isBrowserUrlValid: [
            (s) => [s.browserUrl],
            (browserUrl) => {
                if (!browserUrl) {
                    // an empty browserUrl is valid
                    // since we just won't do anything with it
                    return true
                }

                try {
                    // must be something that can be parsed as a URL
                    new URL(browserUrl)
                    // and must be a valid URL that our redirects can cope with
                    // this is a very loose check, but `http:/blaj` is not valid for PostHog
                    // but survives new URL(http:/blaj)
                    return browserUrl.includes('://')
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

    listeners(({ actions, cache, props, values }) => ({
        setReplayIframeData: ({ replayIframeData }) => {
            if (replayIframeData && replayIframeData.url) {
                actions.setHref(replayIframeData.url)
                // TODO we need to be able to handle regex values
                actions.setHrefMatchType('exact')
            } else {
                removeReplayIframeDataFromLocalStorage()
            }
        },

        setBrowserSearch: async (_, breakpoint) => {
            await breakpoint(200)
            actions.loadBrowserSearchResults()
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
            // it should be impossible to load an iframe without a browserUrl
            // right?!
            actions.setHref(values.browserUrl ?? '')
            actions.loadHeatmap()
            posthog.capture('in-app heatmap iframe loaded', {
                inapp_heatmap_page_url_visited: values.browserUrl,
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
                // TODO we need to be able to handle regex values
                actions.setHrefMatchType('exact')
            }
        },

        setBrowserUrl: ({ url }) => {
            actions.maybeLoadTopUrls()
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
        } else {
            actions.maybeLoadTopUrls()
        }
    }),

    urlToAction(({ actions, values }) => ({
        '/heatmaps': (_, searchParams) => {
            if (searchParams.pageURL && searchParams.pageURL !== values.browserUrl) {
                actions.setBrowserUrl(searchParams.pageURL)
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
            if (searchParams.iframeStorage) {
                const replayFrameData = JSON.parse(
                    localStorage.getItem(searchParams.iframeStorage) || '{}'
                ) as ReplayIframeData
                actions.setReplayIframeData(replayFrameData)
            }
        },
    })),

    actionToUrl(({ values }) => ({
        setBrowserUrl: ({ url }) => {
            const searchParams = { ...router.values.searchParams, pageURL: url }
            if (!url || url.trim() === '') {
                delete searchParams.pageURL
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
])
