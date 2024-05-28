import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { authorizedUrlListLogic, AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { HeatmapFilters, HeatmapFixedPositionMode } from 'lib/components/heatmaps/types'
import { calculateViewportRange, DEFAULT_HEATMAP_FILTERS, PostHogAppToolbarEvent } from 'lib/components/heatmaps/utils'
import { RefObject } from 'react'

import { HogQLQuery, NodeKind } from '~/queries/schema'
import { hogql } from '~/queries/utils'

import type { heatmapsBrowserLogicType } from './heatmapsBrowserLogicType'

export type HeatmapsBrowserLogicProps = {
    iframeRef: RefObject<HTMLIFrameElement | null>
}

export const heatmapsBrowserLogic = kea<heatmapsBrowserLogicType>([
    path(['scenes', 'heatmaps', 'heatmapsBrowserLogic']),
    props({} as HeatmapsBrowserLogicProps),

    connect({
        values: [
            authorizedUrlListLogic({ actionId: null, type: AuthorizedUrlListType.TOOLBAR_URLS }),
            ['urlsKeyed', 'checkUrlIsAuthorized'],
        ],
    }),

    actions({
        setBrowserSearch: (searchTerm: string) => ({ searchTerm }),
        setBrowserUrl: (url: string) => ({ url }),
        setIframePosthogJsConnected: (ready: boolean) => ({ ready }),
        onIframeLoad: true,
        onIframeToolbarLoad: true,
        sendToolbarMessage: (type: PostHogAppToolbarEvent, payload?: Record<string, any>) => ({
            type,
            payload,
        }),
        setLoading: (loading: boolean) => ({ loading }),
        loadTopUrls: true,
        maybeLoadTopUrls: true,
        loadBrowserSearchResults: true,
        // TODO duplicated with the heatmapLogic
        patchHeatmapFilters: (filters: Partial<HeatmapFilters>) => ({ filters }),
        setHeatmapColorPalette: (Palette: string | null) => ({ Palette }),
        setHeatmapFixedPositionMode: (mode: HeatmapFixedPositionMode) => ({ mode }),
        // TODO duplication ends
        setIframeWidth: (width: number | null) => ({ width }),
    }),

    loaders(({ values }) => ({
        browserSearchResults: [
            null as string[] | null,
            {
                loadBrowserSearchResults: async () => {
                    if (!values.browserSearchTerm) {
                        return []
                    }

                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: hogql`SELECT distinct properties.$current_url AS urls
                                FROM events
                                WHERE timestamp >= now() - INTERVAL 7 DAY
                                AND timestamp <= now()
                                AND properties.$current_url like '%${hogql.identifier(values.browserSearchTerm)}%'
                                ORDER BY timestamp DESC
                                limit 100`,
                    }

                    const res = await api.query(query)

                    return res.results?.map((x) => x[0]) as string[]
                },
            },
        ],

        topUrls: [
            null as { url: string; count: number }[] | null,
            {
                loadTopUrls: async () => {
                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: hogql`SELECT properties.$current_url AS url, count() as count FROM events
                                WHERE timestamp >= now() - INTERVAL 7 DAY
                                AND event in ('$pageview', '$autocapture')
                                AND timestamp <= now()
                                GROUP BY properties.$current_url
                                ORDER BY count DESC
                                LIMIT 10`,
                    }

                    const res = await api.query(query)

                    return res.results?.map((x) => ({ url: x[0], count: x[1] })) as { url: string; count: number }[]
                },
            },
        ],
    })),

    reducers({
        // TODO duplicated with the heatmapLogic
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
        // TODO duplication ends
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
            { persist: true },
            {
                setBrowserUrl: (_, { url }) => url,
            },
        ],
        iframePosthogJsConnected: [
            false as boolean,
            {
                setIframePosthogJsConnected: (_, { ready }) => ready,
            },
        ],

        loading: [
            false as boolean,
            {
                setLoading: (_, { loading }) => loading,
                setBrowserUrl: () => true,
                onIframeToolbarLoad: () => false,
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

    listeners(({ actions, props, values }) => ({
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

        onIframeLoad: () => {
            // TODO: Add a timeout - if we haven't received a message from the iframe in X seconds, show an error
            const init = (): void => {
                actions.sendToolbarMessage(PostHogAppToolbarEvent.PH_APP_INIT)
                actions.sendToolbarMessage(PostHogAppToolbarEvent.PH_HEATMAPS_CONFIG, {
                    enabled: true,
                })
            }

            const onIframeMessage = (e: MessageEvent): void => {
                // TODO: Probably need to have strict checks here
                const type: PostHogAppToolbarEvent = e?.data?.type

                if (!type || !type.startsWith('ph-')) {
                    return
                }

                switch (type) {
                    case PostHogAppToolbarEvent.PH_TOOLBAR_INIT:
                        return init()
                    case PostHogAppToolbarEvent.PH_TOOLBAR_READY:
                        return actions.onIframeToolbarLoad()
                    default:
                        console.warn(`[PostHog Heatmpas] Received unknown child window message: ${type}`)
                }
            }

            window.addEventListener('message', onIframeMessage, false)
            // We call init in case the toolbar got there first (unlikely)
            init()
        },

        maybeLoadTopUrls: () => {
            if (!values.topUrls && !values.topUrlsLoading) {
                actions.loadTopUrls()
            }
        },

        setBrowserUrl: () => {
            actions.maybeLoadTopUrls()
        },
    })),

    afterMount(({ actions, values }) => {
        if (values.browserUrl) {
            actions.setLoading(true)
        } else {
            actions.maybeLoadTopUrls()
        }
    }),
])
