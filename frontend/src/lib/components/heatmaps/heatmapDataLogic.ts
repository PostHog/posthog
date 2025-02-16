import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { encodeParams } from 'kea-router'
import { windowValues } from 'kea-window-values'
import {
    CommonFilters,
    HeatmapFilters,
    HeatmapFixedPositionMode,
    HeatmapJsData,
    HeatmapJsDataPoint,
    HeatmapRequestType,
} from 'lib/components/heatmaps/types'
import { calculateViewportRange, DEFAULT_HEATMAP_FILTERS } from 'lib/components/IframedToolbarBrowser/utils'
import { LemonSelectOption } from 'lib/lemon-ui/LemonSelect'
import { dateFilterToText } from 'lib/utils'

import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { HeatmapElement, HeatmapResponseType } from '~/toolbar/types'
import { FilterType } from '~/types'

import type { heatmapDataLogicType } from './heatmapDataLogicType'

export const HEATMAP_COLOR_PALETTE_OPTIONS: LemonSelectOption<string>[] = [
    { value: 'default', label: 'Default (multicolor)' },
    { value: 'red', label: 'Red (monocolor)' },
    { value: 'green', label: 'Green (monocolor)' },
    { value: 'blue', label: 'Blue (monocolor)' },
]

export const heatmapDataLogic = kea<heatmapDataLogicType>([
    path(['lib', 'components', 'heatmap', 'heatmapDataLogic']),
    actions({
        setCommonFilters: (filters: CommonFilters) => ({ filters }),
        setHeatmapFilters: (filters: HeatmapFilters) => ({ filters }),
        patchHeatmapFilters: (filters: Partial<HeatmapFilters>) => ({ filters }),
        loadHeatmap: true,
        fetchHeatmapApi: (params: HeatmapRequestType) => ({ params }),
        setHeatmapFixedPositionMode: (mode: HeatmapFixedPositionMode) => ({ mode }),
        setHeatmapColorPalette: (Palette: string | null) => ({ Palette }),
        setHref: (href: string) => ({ href }),
        setUrlMatch: (match: 'exact' | 'regex') => ({
            match,
        }),
        setFetchFn: (fetchFn: 'native' | 'toolbar') => ({ fetchFn }),
        setHeatmapScrollY: (scrollY: number) => ({ scrollY }),
    }),
    windowValues(() => ({
        windowWidth: (window: Window) => window.innerWidth,
        windowHeight: (window: Window) => window.innerHeight,
    })),
    reducers({
        // TODO with toolbar on the posthog page as well as the page itself, this will clash
        // need to make a separate data logic for toolbar and page
        fetchFn: [
            'toolbar' as 'toolbar' | 'native',
            {
                setFetchFn: (_, { fetchFn }) => fetchFn,
            },
        ],
        commonFilters: [
            { date_from: '-7d' } as CommonFilters,
            {
                setCommonFilters: (_, { filters }) => filters,
            },
        ],
        heatmapFilters: [
            DEFAULT_HEATMAP_FILTERS,
            { persist: true },
            {
                setHeatmapFilters: (_, { filters }) => filters,
                patchHeatmapFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        heatmapFixedPositionMode: [
            'fixed' as HeatmapFixedPositionMode,
            {
                setHeatmapFixedPositionMode: (_, { mode }) => mode,
            },
        ],
        heatmapColorPalette: [
            'default' as string | null,
            { persist: true },
            {
                setHeatmapColorPalette: (_, { Palette }) => Palette,
            },
        ],
        href: [
            null as string | null,
            {
                setHref: (_, { href }) => href,
            },
        ],
        urlMatch: [
            'exact' as 'exact' | 'regex',
            {
                setUrlMatch: (_, { match }) => match,
            },
        ],
        heatmapScrollY: [
            0,
            {
                setHeatmapScrollY: (_, { scrollY }) => scrollY,
            },
        ],
    }),
    loaders(({ values }) => ({
        rawHeatmap: [
            null as HeatmapResponseType | null,
            {
                resetHeatmapData: () => ({ results: [] }),
                loadHeatmap: async () => {
                    const href = values.href
                    const matchType = values.urlMatch
                    const { date_from, date_to } = values.commonFilters
                    const { type, aggregation } = values.heatmapFilters
                    const urlExact = matchType === 'exact' ? href : undefined
                    const urlRegex = matchType === 'regex' ? href : undefined

                    // toolbar fetch collapses queryparams but this URL has multiple with the same name
                    const apiURL = `/api/heatmap/${encodeParams(
                        {
                            type,
                            date_from,
                            date_to,
                            url_exact: urlExact,
                            url_pattern: urlRegex,
                            viewport_width_min: values.viewportRange.min,
                            viewport_width_max: values.viewportRange.max,
                            aggregation,
                        },
                        '?'
                    )}`

                    const response = await (values.fetchFn === 'toolbar' ? toolbarFetch(apiURL, 'GET') : fetch(apiURL))

                    if (response.status === 403) {
                        toolbarConfigLogic.actions.authenticate()
                    }

                    if (response.status !== 200) {
                        throw new Error('API error')
                    }

                    return await response.json()
                },
            },
        ],
    })),
    selectors({
        dateRange: [
            (s) => [s.commonFilters],
            (commonFilters: Partial<FilterType>) => {
                return dateFilterToText(commonFilters.date_from, commonFilters.date_to, 'Last 7 days')
            },
        ],

        heatmapElements: [
            (s) => [s.rawHeatmap],
            (rawHeatmap): HeatmapElement[] => {
                if (!rawHeatmap) {
                    return []
                }

                const elements: HeatmapElement[] = []

                rawHeatmap?.results.forEach((element) => {
                    if ('scroll_depth_bucket' in element) {
                        elements.push({
                            count: element.cumulative_count,
                            xPercentage: 0,
                            targetFixed: false,
                            y: element.scroll_depth_bucket,
                        })
                    } else {
                        elements.push({
                            count: element.count,
                            xPercentage: element.pointer_relative_x,
                            targetFixed: element.pointer_target_fixed,
                            y: element.pointer_y,
                        })
                    }
                })

                return elements
            },
        ],

        viewportRange: [
            (s) => [s.heatmapFilters, s.windowWidth],
            (heatmapFilters, windowWidth) => calculateViewportRange(heatmapFilters, windowWidth),
        ],

        heatmapTooltipLabel: [
            (s) => [s.heatmapFilters],
            (heatmapFilters) => {
                if (heatmapFilters.aggregation === 'unique_visitors') {
                    return 'visitors'
                }
                return heatmapFilters.type + 's'
            },
        ],

        heatmapJsData: [
            (s) => [s.heatmapElements, s.heatmapScrollY, s.windowWidth, s.heatmapFixedPositionMode],
            (heatmapElements, heatmapScrollY, windowWidth, heatmapFixedPositionMode): HeatmapJsData => {
                // We want to account for all the fixed position elements, the scroll of the context and the browser width
                const data = heatmapElements.reduce((acc, element) => {
                    if (heatmapFixedPositionMode === 'hidden' && element.targetFixed) {
                        return acc
                    }

                    const y = Math.round(
                        element.targetFixed && heatmapFixedPositionMode === 'fixed'
                            ? element.y
                            : element.y - heatmapScrollY
                    )
                    const x = Math.round(element.xPercentage * windowWidth)

                    return [...acc, { x, y, value: element.count }]
                }, [] as HeatmapJsDataPoint[])

                // Max is the highest value in the data set we have
                const max = data.reduce((max, { value }) => Math.max(max, value), 0)

                // TODO: Group based on some sensible resolutions (we can then use this for a hover state to show more detail)

                return {
                    min: 0,
                    max,
                    data,
                }
            },
        ],
    }),
    listeners(({ actions }) => ({
        fetchHeatmapApi: ({ params }) => {
            // TODO need to be able to pass or set these params
            actions.loadHeatmap(params.type)
        },
    })),
])
