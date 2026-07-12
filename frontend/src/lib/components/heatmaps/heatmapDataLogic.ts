import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { encodeParams } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import { windowValues } from 'kea-window-values'

import {
    CommonFilters,
    HeatmapArea,
    HeatmapBoundsFilter,
    HeatmapEventsResponse,
    HeatmapFilters,
    HeatmapFixedPositionMode,
    HeatmapJsData,
    HeatmapJsDataPoint,
} from 'lib/components/heatmaps/types'
import {
    DEFAULT_HEATMAP_FILTERS,
    DEFAULT_HEATMAP_HEIGHT,
    DEFAULT_HEATMAP_WIDTH,
    calculateViewportRange,
} from 'lib/components/IframedToolbarBrowser/utils'
import { LemonSelectOption } from 'lib/lemon-ui/LemonSelect'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { dateFilterToText } from 'lib/utils/dateFilters'
import { getAppContext } from 'lib/utils/getAppContext'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { toolbarFetch } from '~/toolbar/toolbarFetch'
import { ToolbarRequestError } from '~/toolbar/toolbarRequestError'
import { HeatmapElement, HeatmapResponseType } from '~/toolbar/types'
import { FilterType } from '~/types'

import type { heatmapDataLogicType } from './heatmapDataLogicType'

// The endpoint defaults to a bounded page for API callers; the overlay renders every point.
const UNBOUNDED_HEATMAP_LIMIT = 0

export const HEATMAP_COLOR_PALETTE_OPTIONS: LemonSelectOption<string>[] = [
    { value: 'default', label: 'Default (multicolor)' },
    { value: 'red', label: 'Red (monocolor)' },
    { value: 'green', label: 'Green (monocolor)' },
    { value: 'blue', label: 'Blue (monocolor)' },
]

async function parseHeatmapErrorMessage(response: Response): Promise<string> {
    try {
        const body = await response.clone().json()
        if (typeof body?.detail === 'string' && body.detail.length > 0) {
            return body.detail
        }
        for (const value of Object.values(body ?? {})) {
            if (Array.isArray(value) && typeof value[0] === 'string') {
                return value[0]
            }
            if (typeof value === 'string' && value.length > 0) {
                return value
            }
        }
    } catch {
        /* empty */
    }
    return `Heatmap request failed (status ${response.status})`
}

export interface HeatmapDataLogicProps {
    context: 'in-app' | 'toolbar'
    exportToken?: string | null
}

/**
 * Fetch a heatmap endpoint and raise request failures the right way for each context:
 * in the toolbar a failed request is an expected outcome, so it becomes a tagged
 * `ToolbarRequestError` (drives the loader's *Failure action without being reported to
 * error tracking); in-app the pre-existing plain-error behavior is preserved.
 */
async function fetchHeatmapData(
    props: HeatmapDataLogicProps,
    apiURL: string,
    options: { authenticateOn403?: boolean } = {}
): Promise<Response> {
    let response: Response
    try {
        response = await (props.context === 'toolbar'
            ? toolbarFetch(apiURL, 'GET')
            : props.exportToken
              ? fetch(apiURL, { headers: { Authorization: `Bearer ${props.exportToken}` } })
              : fetch(apiURL))
    } catch (e) {
        if (props.context === 'toolbar') {
            throw new ToolbarRequestError('Network error while loading heatmap data')
        }
        throw e
    }

    if (props.context === 'toolbar' && response.status === 403 && options.authenticateOn403) {
        toolbarConfigLogic.actions.authenticate()
    }

    if (response.status !== 200) {
        const message = await parseHeatmapErrorMessage(response)
        if (props.context === 'toolbar') {
            throw new ToolbarRequestError(message, response.status)
        }
        throw new Error(message)
    }

    return response
}

export function heatmapApiPath(context: HeatmapDataLogicProps['context'], endpoint: '' | 'events/'): string {
    if (context === 'in-app') {
        // The unscoped /api/heatmap/ route resolves the team from the user's *global* current
        // project, which any other tab can change, so pin the team this page was loaded for
        // instead. The app context team is also set on export renders (team_for_public_context).
        const teamId = getAppContext()?.current_team?.id
        if (teamId != null) {
            return `/api/projects/${teamId}/heatmaps/${endpoint}`
        }
    }
    return `/api/heatmap/${endpoint}`
}

export type HrefMatchType = 'exact' | 'pattern'

export function isWithinBounds(
    point: { x: number; y: number; targetFixed: boolean },
    boundsFilter: HeatmapBoundsFilter | null
): boolean {
    if (!boundsFilter) {
        return true
    }
    // points and areas live in different coordinate spaces depending on fixedness, so a
    // point of the other kind can't be meaningfully tested against this area — exclude it
    if (point.targetFixed !== boundsFilter.areaFixed) {
        return false
    }
    const { bounds } = boundsFilter
    return point.x >= bounds.left && point.x <= bounds.right && point.y >= bounds.top && point.y <= bounds.bottom
}

export const heatmapDataLogic = kea<heatmapDataLogicType>([
    path((key) => ['lib', 'components', 'heatmap', 'heatmapDataLogic', key]),
    props({ context: 'toolbar', exportToken: null } as HeatmapDataLogicProps),
    key((props) => props.context),
    actions({
        loadHeatmap: true,
        setCommonFilters: (filters: CommonFilters) => ({ filters }),
        setHeatmapFilters: (filters: HeatmapFilters) => ({ filters }),
        patchHeatmapFilters: (filters: Partial<HeatmapFilters>) => ({ filters }),
        setHeatmapFixedPositionMode: (mode: HeatmapFixedPositionMode) => ({ mode }),
        setHeatmapColorPalette: (palette: string | null) => ({ palette }),
        setHeatmapTooltipSuppressed: (suppressed: boolean) => ({ suppressed }),
        setHref: (href: string) => ({ href }),
        setHrefMatchType: (matchType: HrefMatchType) => ({ matchType }),
        setWindowWidthOverride: (widthOverride: number | null) => ({ widthOverride }),
        setHeatmapBoundsFilter: (boundsFilter: HeatmapBoundsFilter | null) => ({ boundsFilter }),
        setIsReady: (isReady: boolean) => ({ isReady }),
        // Click-to-view-events actions
        setSelectedArea: (area: HeatmapArea | null) => ({ area }),
        clearSelectedArea: true,
        setShowEventsPanel: (show: boolean) => ({ show }),
        loadMoreAreaEvents: true,
        loadMoreAreaEventsSuccess: (payload: HeatmapEventsResponse) => ({ payload }),
    }),
    windowValues(() => ({
        windowWidth: (window: Window) => window.innerWidth,
        windowHeight: (window: Window) => window.innerHeight,
    })),
    reducers({
        hrefMatchType: [
            'exact' as HrefMatchType,
            {
                setHrefMatchType: (_, { matchType }) => matchType,
            },
        ],
        commonFilters: [
            { date_from: '-7d' } as CommonFilters,
            { persist: true },
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
            { persist: true },
            {
                setHeatmapFixedPositionMode: (_, { mode }) => mode,
            },
        ],
        heatmapColorPalette: [
            'default' as string | null,
            { persist: true },
            {
                setHeatmapColorPalette: (_, { palette }) => palette,
            },
        ],
        // e.g. while the clickmap overlay shows its own element tooltip
        heatmapTooltipSuppressed: [
            false,
            {
                setHeatmapTooltipSuppressed: (_, { suppressed }) => suppressed,
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
        windowWidthOverride: [
            null as number | null,
            { persist: true },
            {
                setWindowWidthOverride: (_, { widthOverride }) => widthOverride,
            },
        ],
        // deliberately not persisted: the bounds describe an element on the page currently
        // being viewed, so they'd be meaningless (and misleading) on the next page
        heatmapBoundsFilter: [
            null as HeatmapBoundsFilter | null,
            {
                setHeatmapBoundsFilter: (_, { boundsFilter }) => boundsFilter,
            },
        ],
        isReady: [
            false as boolean,
            {
                setIsReady: (_, { isReady }) => isReady,
            },
        ],
        selectedArea: [
            null as HeatmapArea | null,
            {
                setSelectedArea: (_, { area }) => area,
                clearSelectedArea: () => null,
            },
        ],
        showEventsPanel: [
            false as boolean,
            {
                setShowEventsPanel: (_, { show }) => show,
                clearSelectedArea: () => false,
            },
        ],
        areaEventsLoadingMore: [
            false as boolean,
            {
                loadMoreAreaEvents: () => true,
                loadMoreAreaEventsSuccess: () => false,
            },
        ],
        // Additional reducers for areaEvents (loader is defined below)
        areaEvents: [
            null as HeatmapEventsResponse | null,
            {
                loadMoreAreaEventsSuccess: (_, { payload }) => payload,
                clearSelectedArea: () => null,
            },
        ],
    }),
    loaders(({ values, props, actions }) => ({
        rawHeatmap: [
            null as HeatmapResponseType | null,
            {
                resetHeatmapData: () => ({ results: [] }),
                loadHeatmap: async (_, breakpoint) => {
                    await breakpoint(150)

                    if (!values.href || !values.href.trim().length) {
                        return null
                    }
                    if (!values.heatmapFilters.enabled) {
                        return null
                    }

                    actions.setIsReady(false)

                    const { date_from, date_to, filter_test_accounts, cohort_ids } = values.commonFilters
                    const { type, aggregation } = values.heatmapFilters

                    // toolbar fetch collapses queryparams but this URL has multiple with the same name
                    const apiURL = `${heatmapApiPath(props.context, '')}${encodeParams(
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
                            cohort_ids: cohort_ids && cohort_ids.length > 0 ? cohort_ids : undefined,
                            limit: UNBOUNDED_HEATMAP_LIMIT,
                        },
                        '?'
                    )}`

                    // if we export the heatmap, we need to add the export token to the headers
                    const response = await fetchHeatmapData(props, apiURL, { authenticateOn403: true })
                    breakpoint()

                    const data = await response.json()
                    actions.setIsReady(true)
                    return data
                },
            },
        ],
        areaEvents: [
            null as HeatmapEventsResponse | null,
            {
                loadAreaEvents: async (_, breakpoint) => {
                    const area = values.selectedArea
                    if (!area || !values.href) {
                        return null
                    }

                    await breakpoint(100)

                    const { date_from, date_to, filter_test_accounts, cohort_ids } = values.commonFilters
                    const { type } = values.heatmapFilters

                    const apiURL = `${heatmapApiPath(props.context, 'events/')}${encodeParams(
                        {
                            type,
                            date_from,
                            date_to,
                            url_exact: values.hrefMatchType === 'exact' ? values.href : undefined,
                            url_pattern: values.hrefMatchType === 'pattern' ? values.href : undefined,
                            viewport_width_min: values.viewportRange.min,
                            viewport_width_max: values.viewportRange.max,
                            filter_test_accounts,
                            cohort_ids: cohort_ids && cohort_ids.length > 0 ? cohort_ids : undefined,
                            points: JSON.stringify(area.points),
                        },
                        '?'
                    )}`

                    const response = await fetchHeatmapData(props, apiURL)
                    breakpoint()

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

        // Derived width with default applied
        widthOverride: [
            (s) => [s.windowWidthOverride],
            (windowWidthOverride: number | null): number => windowWidthOverride ?? DEFAULT_HEATMAP_WIDTH,
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

        maxYFromEvents: [
            (s) => [s.heatmapElements],
            (heatmapElements: HeatmapElement[]): number => {
                if (!heatmapElements || heatmapElements.length === 0) {
                    return 0
                }
                return Math.max(...heatmapElements.map((el: HeatmapElement) => el.y))
            },
        ],

        // Derived height - maximum of calculated height from events and viewport height
        heightOverride: [
            (s) => [s.maxYFromEvents, s.windowHeight],
            (maxYFromEvents: number, windowHeight: number): number => {
                // Limit canvas height to prevent browser freezing with heatmap.js
                // Large canvases (e.g., 24000px) cause heatmap.js to block the main thread
                const MAX_HEATMAP_HEIGHT = 8000
                if (maxYFromEvents > 0) {
                    const calculatedHeight = Math.ceil((maxYFromEvents + 100) / 100) * 100
                    return Math.min(Math.max(calculatedHeight, windowHeight), MAX_HEATMAP_HEIGHT)
                }
                return Math.max(DEFAULT_HEATMAP_HEIGHT, windowHeight)
            },
        ],

        // the one place the area bounds filter applies, so rendering (heatmapJsData) and
        // click-to-view-events hit testing can't disagree about which points exist
        filteredHeatmapElements: [
            (s) => [s.heatmapElements, s.windowWidth, s.windowWidthOverride, s.heatmapBoundsFilter],
            (heatmapElements, windowWidth, windowWidthOverride, heatmapBoundsFilter): HeatmapElement[] => {
                if (!heatmapBoundsFilter) {
                    return heatmapElements
                }
                const width = windowWidthOverride ?? windowWidth
                return heatmapElements.filter((element) =>
                    isWithinBounds(
                        {
                            x: Math.round(element.xPercentage * width),
                            y: Math.round(element.y),
                            targetFixed: element.targetFixed,
                        },
                        heatmapBoundsFilter
                    )
                )
            },
        ],

        heatmapJsData: [
            (s) => [s.filteredHeatmapElements, s.windowWidth, s.windowWidthOverride, s.heatmapFixedPositionMode],
            (filteredHeatmapElements, windowWidth, windowWidthOverride, heatmapFixedPositionMode): HeatmapJsData => {
                const width = windowWidthOverride ?? windowWidth
                const data = filteredHeatmapElements.reduce((acc, element) => {
                    if (heatmapFixedPositionMode === 'hidden' && element.targetFixed) {
                        return acc
                    }

                    const y = Math.round(element.y)
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
    listeners(({ actions, values, props }) => ({
        setCommonFilters: () => {
            actions.loadHeatmap()
        },
        setHeatmapFilters: () => {
            actions.loadHeatmap()
        },
        patchHeatmapFilters: ({ filters }) => {
            // Clear old data when switching heatmap types
            if (filters.type) {
                actions.resetHeatmapData()
            }
            actions.loadHeatmap()
        },
        setHref: () => {
            actions.loadHeatmap()
        },
        setWindowWidthOverride: () => {
            actions.loadHeatmap()
        },
        setSelectedArea: ({ area }) => {
            if (area) {
                actions.loadAreaEvents({})
                actions.setShowEventsPanel(true)
            }
        },
        loadMoreAreaEvents: async () => {
            const area = values.selectedArea
            const currentEvents = values.areaEvents
            if (!area || !values.href || !currentEvents?.results) {
                return
            }

            const { date_from, date_to, filter_test_accounts, cohort_ids } = values.commonFilters
            const { type } = values.heatmapFilters
            const nextOffset = currentEvents.results.length

            const apiURL = `${heatmapApiPath(props.context, 'events/')}${encodeParams(
                {
                    type,
                    date_from,
                    date_to,
                    url_exact: values.hrefMatchType === 'exact' ? values.href : undefined,
                    url_pattern: values.hrefMatchType === 'pattern' ? values.href : undefined,
                    viewport_width_min: values.viewportRange.min,
                    viewport_width_max: values.viewportRange.max,
                    filter_test_accounts,
                    cohort_ids: cohort_ids && cohort_ids.length > 0 ? cohort_ids : undefined,
                    points: JSON.stringify(area.points),
                    offset: nextOffset,
                },
                '?'
            )}`

            let response: Response
            try {
                response = await fetchHeatmapData(props, apiURL)
            } catch (e) {
                lemonToast.error(e instanceof Error ? e.message : 'Failed to load more events')
                return
            }

            const newData: HeatmapEventsResponse = await response.json()

            actions.loadMoreAreaEventsSuccess({
                results: [...currentEvents.results, ...(newData.results || [])],
                total_count: newData.total_count,
                has_more: newData.has_more,
            })
        },
        loadHeatmapFailure: ({ error }) => {
            lemonToast.error(error || 'Heatmap query failed')
            actions.setIsReady(true)
        },
        loadAreaEventsFailure: ({ error }) => {
            lemonToast.error(error || 'Failed to load events for selected area')
        },
    })),
    subscriptions(({ actions }) => ({
        windowWidth: () => {
            actions.loadHeatmap()
        },
        windowHeight: () => {
            actions.loadHeatmap()
        },
    })),
])
