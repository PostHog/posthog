import { actions, kea, listeners, path, props, reducers, selectors, key } from 'kea'
import { loaders } from 'kea-loaders'
import { encodeParams } from 'kea-router'
import { windowValues } from 'kea-window-values'
import {
    CommonFilters,
    HeatmapFilters,
    HeatmapFixedPositionMode,
    HeatmapJsData,
    HeatmapJsDataPoint,
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

export interface HeatmapDataLogicProps {
    context: 'in-app' | 'toolbar'
}

export const heatmapDataLogic = kea<heatmapDataLogicType>([
    path((key) => ['lib', 'components', 'heatmap', 'heatmapDataLogic', key]),
    props({ context: 'toolbar' } as HeatmapDataLogicProps),
    key((props) => props.context),
    actions({
        loadHeatmap: true,
        setCommonFilters: (filters: CommonFilters) => ({ filters }),
        setHeatmapFilters: (filters: HeatmapFilters) => ({ filters }),
        patchHeatmapFilters: (filters: Partial<HeatmapFilters>) => ({ filters }),
        setHeatmapFixedPositionMode: (mode: HeatmapFixedPositionMode) => ({ mode }),
        setHeatmapColorPalette: (Palette: string | null) => ({ Palette }),
        setHref: (href: string) => ({ href }),
        setHrefMatchType: (matchType: 'exact' | 'pattern') => ({ matchType }),
        setHeatmapScrollY: (scrollY: number) => ({ scrollY }),
        setWindowWidthOverride: (widthOverride: number | null) => ({ widthOverride }),
    }),
    windowValues(() => ({
        windowWidth: (window: Window) => window.innerWidth,
        windowHeight: (window: Window) => window.innerHeight,
    })),
    reducers({
        hrefMatchType: [
            'exact' as 'exact' | 'pattern',
            {
                setHrefMatchType: (_, { matchType }) => matchType,
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
                setHref: (_, { href }) => {
                    return href
                },
            },
        ],
        heatmapScrollY: [
            0,
            {
                setHeatmapScrollY: (_, { scrollY }) => scrollY,
            },
        ],
        windowWidthOverride: [
            null as number | null,
            {
                setWindowWidthOverride: (_, { widthOverride }) => widthOverride,
            },
        ],
    }),
    loaders(({ values, props }) => ({
        rawHeatmap: [
            null as HeatmapResponseType | null,
            {
                resetHeatmapData: () => ({ results: [] }),
                loadHeatmap: async (_, breakpoint) => {
                    if (!values.href || !values.href.trim().length) {
                        return null
                    }
                    if (!values.heatmapFilters.enabled) {
                        return null
                    }
                    await breakpoint(150)

                    const { date_from, date_to, filter_test_accounts } = values.commonFilters
                    const { type, aggregation } = values.heatmapFilters

                    // toolbar fetch collapses queryparams but this URL has multiple with the same name
                    const apiURL = `/api/heatmap/${encodeParams(
                        {
                            type,
                            date_from,
                            date_to,
                            url_exact: values.hrefMatchType === 'exact' ? values.href : undefined,
                            url_pattern: values.hrefMatchType === 'pattern' ? values.href : undefined,
                            viewport_width_min: values.viewportRange.min,
                            viewport_width_max: values.viewportRange.max,
                            aggregation,
                            filter_test_accounts,
                        },
                        '?'
                    )}`

                    const response = await (props.context === 'toolbar' ? toolbarFetch(apiURL, 'GET') : fetch(apiURL))
                    breakpoint()

                    if (props.context === 'toolbar' && response.status === 403) {
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
            (s) => [s.heatmapFilters, s.windowWidth, s.windowWidthOverride],
            (heatmapFilters, windowWidth, windowWidthOverride) =>
                calculateViewportRange(heatmapFilters, windowWidthOverride ?? windowWidth),
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

        heatmapEmpty: [
            (s) => [s.rawHeatmap, s.rawHeatmapLoading],
            (rawHeatmap, rawHeatmapLoading) => {
                return rawHeatmap?.results.length === 0 && !rawHeatmapLoading
            },
        ],

        heatmapJsData: [
            (s) => [
                s.heatmapElements,
                s.heatmapScrollY,
                s.windowWidth,
                s.windowWidthOverride,
                s.heatmapFixedPositionMode,
            ],
            (
                heatmapElements,
                heatmapScrollY,
                windowWidth,
                windowWidthOverride,
                heatmapFixedPositionMode
            ): HeatmapJsData => {
                const width = windowWidthOverride ?? windowWidth
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
                    const x = Math.round(element.xPercentage * width)

                    acc.push({ x, y, value: element.count })
                    return acc
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
        setCommonFilters: () => {
            actions.loadHeatmap()
        },
        setHeatmapFilters: () => {
            actions.loadHeatmap()
        },
        patchHeatmapFilters: () => {
            actions.loadHeatmap()
        },
        setHeatmapFixedPositionMode: () => {
            actions.loadHeatmap()
        },
        setHeatmapColorPalette: () => {
            actions.loadHeatmap()
        },
        setHref: () => {
            actions.loadHeatmap()
        },
        setWindowWidthOverride: () => {
            actions.loadHeatmap()
        },
    })),
])
