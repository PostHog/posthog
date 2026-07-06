import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import { windowValues } from 'kea-window-values'
import { PostHog } from 'posthog-js'
import { collectAllElementsDeep } from 'query-selector-shadow-dom'

import type { PaginatedResponse } from 'lib/api'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { HeatmapBoundsFilter } from 'lib/components/heatmaps/types'
import { createVersionChecker } from 'lib/utils/semver'

import {
    DOMIndex,
    buildDOMIndex,
    hasNonToolbarShadowRoots,
    matchEventToElementUsingIndex,
    matchEventToElementUsingSelectors,
} from '~/toolbar/elements/domElementIndex'
import { productToursLogic } from '~/toolbar/product-tours/productToursLogic'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { toolbarApi } from '~/toolbar/toolbarApi'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { CountedHTMLElement, ElementsEventType } from '~/toolbar/types'
import {
    elementIsVisible,
    elementToActionStep,
    getParent,
    getToolbarRootElement,
    invalidateZoomCache,
    trimElement,
} from '~/toolbar/utils'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { heatmapToolbarMenuLogicType } from './heatmapToolbarMenuLogicType'

export const doesVersionSupportScrollDepth = createVersionChecker('1.99')

const ELEMENT_STATS_PAGE_LIMIT = 5000

// when picking an area to filter to, hovering snaps to the nearest of these semantic
// containers so "the nav" or "the main content" is one click; anything else falls back
// to the hovered element itself. The role variants cover framework/legacy markup that
// skips the semantic tags.
export const AREA_TARGET_SELECTOR = [
    'nav',
    'main',
    'header',
    'footer',
    'aside',
    'section',
    'article',
    'form',
    '[role="navigation"]',
    '[role="main"]',
    '[role="banner"]',
    '[role="contentinfo"]',
].join(', ')

export function resolveAreaTarget(target: HTMLElement): HTMLElement {
    return (target.closest(AREA_TARGET_SELECTOR) as HTMLElement | null) ?? target
}

// area candidates smaller than this are noise — tiny elements stay reachable via the
// arrow keys, and boxing them would bury the containers this mode exists to offer
const AREA_CANDIDATE_MIN_WIDTH_PX = 80
const AREA_CANDIDATE_MIN_HEIGHT_PX = 40
// rendering cost cap: the biggest candidates are the useful ones, so drop the tail
const AREA_CANDIDATE_LIMIT = 300

// every plausible container on the page, rendered as simultaneous hover targets while
// picking (the actions-inspector pattern): semantic containers plus any div that is
// visibly its own region. Same-rect wrapper chains collapse to their deepest element,
// and the result is sorted biggest-first so nested boxes paint children-on-top.
export function computeAreaCandidates(): HTMLElement[] {
    const toolbarRoot = getToolbarRootElement()
    const visibilityCache = new WeakMap<HTMLElement, boolean>()
    const byRectKey = new Map<string, { element: HTMLElement; area: number }>()

    for (const element of collectAllElementsDeep('*', document) as HTMLElement[]) {
        if (toolbarRoot?.contains(element) || !element.matches(`${AREA_TARGET_SELECTOR}, div`)) {
            continue
        }
        const rect = element.getBoundingClientRect()
        if (rect.width < AREA_CANDIDATE_MIN_WIDTH_PX || rect.height < AREA_CANDIDATE_MIN_HEIGHT_PX) {
            continue
        }
        if (!elementIsVisible(element, visibilityCache)) {
            continue
        }
        const key = `${Math.round(rect.top)}:${Math.round(rect.left)}:${Math.round(rect.width)}:${Math.round(rect.height)}`
        // document order visits parents before children, so the last write per rect key
        // keeps the deepest element of a zero-layout wrapper chain
        byRectKey.set(key, { element, area: rect.width * rect.height })
    }

    return Array.from(byRectKey.values())
        .sort((a, b) => b.area - a.area)
        .slice(0, AREA_CANDIDATE_LIMIT)
        .map(({ element }) => element)
}

function rectsMatch(a: DOMRect, b: DOMRect): boolean {
    return (
        Math.abs(a.top - b.top) < 1 &&
        Math.abs(a.left - b.left) < 1 &&
        Math.abs(a.width - b.width) < 1 &&
        Math.abs(a.height - b.height) < 1
    )
}

// arrow-key refinement of the hovered area: "up" grows the selection to the nearest
// ancestor that is visibly bigger, "down" shrinks it back toward the exact hovered
// element (the anchor). Same-size wrapper elements are skipped in both directions so
// every step visibly changes the highlight on div-heavy pages.
export function stepAreaCandidate(anchor: HTMLElement, candidate: HTMLElement, direction: 'up' | 'down'): HTMLElement {
    const candidateRect = candidate.getBoundingClientRect()

    if (direction === 'up') {
        let next = getParent(candidate)
        while (next && next !== document.body && rectsMatch(next.getBoundingClientRect(), candidateRect)) {
            next = getParent(next)
        }
        return next && next !== document.body && next !== document.documentElement ? next : candidate
    }

    if (candidate === anchor) {
        return candidate
    }
    // pointer hover keeps the anchor a descendant of the candidate, so the way down is
    // the chain from the anchor up to just below the candidate; hovering an overlapping
    // candidate box can break that, in which case the guard below makes "down" a no-op
    const path: HTMLElement[] = []
    let current: HTMLElement | null = anchor
    while (current && current !== candidate) {
        path.push(current)
        current = getParent(current)
    }
    if (current !== candidate || path.length === 0) {
        return candidate
    }
    let index = path.length - 1
    while (index > 0 && rectsMatch(path[index].getBoundingClientRect(), candidateRect)) {
        index--
    }
    return path[index]
}

export function buildElementStatsProperties(
    href: string,
    wildcardHref: string,
    areaSelector: string | null
): AnyPropertyFilter[] {
    const properties: AnyPropertyFilter[] = [
        wildcardHref === href
            ? {
                  key: '$current_url',
                  value: href,
                  operator: PropertyOperator.Exact,
                  type: PropertyFilterType.Event,
              }
            : {
                  key: '$current_url',
                  value: `^${wildcardHref.split('*').map(escapeUnescapedRegex).join('.*')}$`,
                  operator: PropertyOperator.Regex,
                  type: PropertyFilterType.Event,
              },
    ]
    if (areaSelector) {
        properties.push({
            key: 'selector',
            value: areaSelector,
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Element,
        })
    }
    return properties
}

// mirrors how posthog-js decides target_fixed when recording heatmap points, so an area
// and its points classify the same way
export function isInFixedContainer(element: HTMLElement): boolean {
    let current: HTMLElement | null = element
    while (current) {
        const position = window.getComputedStyle(current).position
        if (position === 'fixed' || position === 'sticky') {
            return true
        }
        current = getParent(current)
    }
    return false
}

// containment that follows shadow boundaries, unlike Node.contains — the clickmap matcher
// deliberately matches elements inside shadow roots
export function containsInComposedTree(container: HTMLElement, element: HTMLElement): boolean {
    let current: HTMLElement | null = element
    while (current) {
        if (current === container) {
            return true
        }
        current = getParent(current)
    }
    return false
}

function findElementBySelector(selector: string | null): HTMLElement | null {
    if (!selector) {
        return null
    }
    try {
        return document.querySelector(selector) as HTMLElement | null
    } catch {
        // toolbar-derived selectors are not guaranteed to be valid querySelector input
        return null
    }
}

// the single rule for following a filter whose node a re-render replaced — shared by the
// clickmap containment check and the bounds updater so the two can't resolve differently
export function resolveAreaElement(filter: { element: HTMLElement; selector: string | null }): HTMLElement | null {
    return filter.element.isConnected ? filter.element : findElementBySelector(filter.selector)
}

export function computeAreaBounds(element: HTMLElement): HeatmapBoundsFilter {
    const rect = element.getBoundingClientRect()
    const areaFixed = isInFixedContainer(element)
    return {
        areaFixed,
        // fixed/sticky areas compare against viewport-recorded points, so keep the viewport
        // rect; static areas compare against document-recorded points, so add the scroll offset
        bounds: areaFixed
            ? { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom }
            : {
                  left: rect.left + window.scrollX,
                  right: rect.right + window.scrollX,
                  top: rect.top + window.scrollY,
                  bottom: rect.bottom + window.scrollY,
              },
    }
}

// the follow-up fetch re-reads from offset 0 with a bigger limit rather than paginating:
// the server re-runs the full aggregation for any offset, so one big scan costs the same as
// a page and can't miss rows that shifted across page boundaries between scans
const ELEMENT_STATS_AUTO_LOAD_LIMIT = 50000

function yieldToMain(): Promise<void> {
    return new Promise((resolve) => {
        if ('scheduler' in window && typeof (window as any).scheduler?.yield === 'function') {
            ;(window as any).scheduler.yield().then(resolve)
        } else if (typeof (window as any).requestIdleCallback === 'function') {
            ;(window as any).requestIdleCallback(() => resolve(), { timeout: 50 })
        } else {
            setTimeout(resolve, 0)
        }
    })
}

export type ClickmapProcessingTrigger = 'initial' | 'auto-load' | 'pagination' | 'refresh' | 'toggle'

interface ElementProcessingCache {
    pageElements?: HTMLElement[]
    domIndex?: DOMIndex
    selectorToElements: Map<string, HTMLElement[] | null>
    // matched DOM element (or a definitive miss) per type:chain_hash row identity, so the
    // auto-load refetch and pagination reprocess only rows they haven't matched before
    matchedElementByIdentity: Map<string, HTMLElement | null>
    lastHref?: string
    intersectionObserver?: IntersectionObserver
    visibilityCache: WeakMap<HTMLElement, boolean>
    mutationObserver?: MutationObserver
    cacheInvalidated?: boolean
}

function invalidatePageElementsCache(cache: ElementProcessingCache): void {
    cache.cacheInvalidated = true
    cache.visibilityCache = new WeakMap()
    cache.domIndex = undefined
    cache.matchedElementByIdentity = new Map()
}

function getCachedPageElements(
    cache: ElementProcessingCache,
    href: string
): { pageElements: HTMLElement[]; domIndex: DOMIndex; hasShadowRoots: boolean; cacheHit: boolean } {
    const hrefChanged = cache.lastHref !== href
    const cacheValid = cache.pageElements && !hrefChanged && !cache.cacheInvalidated

    if (cacheValid && cache.pageElements && cache.domIndex) {
        // attachShadow() emits no light-DOM mutation, so shadow roots can appear without
        // invalidating the cache; when that happens the snapshot predates the shadow content,
        // so rebuild rather than just flipping the flag over stale data
        if (hasNonToolbarShadowRoots(cache.pageElements) === cache.domIndex.hasShadowRoots) {
            return {
                pageElements: cache.pageElements,
                domIndex: cache.domIndex,
                hasShadowRoots: cache.domIndex.hasShadowRoots,
                cacheHit: true,
            }
        }
    }

    cache.pageElements = collectAllElementsDeep('*', document)
    cache.domIndex = buildDOMIndex(cache.pageElements)
    cache.lastHref = href
    cache.selectorToElements = new Map()
    cache.matchedElementByIdentity = new Map()
    cache.cacheInvalidated = false
    return {
        pageElements: cache.pageElements,
        domIndex: cache.domIndex,
        hasShadowRoots: cache.domIndex.hasShadowRoots,
        cacheHit: false,
    }
}

const emptyElementsStatsPages: PaginatedResponse<ElementsEventType> = {
    next: undefined,
    previous: undefined,
    results: [],
}

export const heatmapToolbarMenuLogic = kea<heatmapToolbarMenuLogicType>([
    path(['toolbar', 'elements', 'heatmapToolbarMenuLogic']),
    connect(() => ({
        values: [
            currentPageLogic,
            ['href', 'wildcardHref'],
            toolbarConfigLogic,
            ['posthog'],
            heatmapDataLogic,
            [
                'commonFilters',
                'heatmapColorPalette',
                'heatmapFixedPositionMode',
                'rawHeatmapLoading',
                'viewportRange',
                'heatmapFilters',
                'heatmapElements',
                'heatmapTooltipLabel',
                'dateRange',
            ],
        ],
        actions: [
            currentPageLogic,
            ['setHref', 'setWildcardHref'],
            heatmapDataLogic,
            [
                'setHeatmapColorPalette',
                'setCommonFilters',
                'setHeatmapFixedPositionMode',
                'setHref as setDataHref',
                'setHrefMatchType',
                'resetHeatmapData',
                'patchHeatmapFilters',
                'loadHeatmap',
                'loadHeatmapSuccess',
                'loadHeatmapFailure',
                'setHeatmapBoundsFilter',
            ],
        ],
    })),
    actions({
        getElementStats: (url?: string | null, limit?: number) => ({
            url,
            limit,
        }),
        enableHeatmap: true,
        disableHeatmap: true,
        toggleClickmapsEnabled: (enabled: boolean) => ({ enabled }),
        setSamplingFactor: (samplingFactor: number) => ({ samplingFactor }),
        loadMoreElementStats: true,
        setMatchLinksByHref: (matchLinksByHref: boolean) => ({ matchLinksByHref }),
        loadAllEnabled: true,
        maybeLoadClickmap: true,
        maybeLoadHeatmap: true,
        updateElementMetrics: (observedElements: [HTMLElement, boolean][]) => ({ observedElements }),
        startElementObservation: true,
        stopElementObservation: true,
        processElements: (trigger: ClickmapProcessingTrigger) => ({ trigger }),
        refreshClickmap: true,
        setIsRefreshing: (isRefreshing: boolean) => ({ isRefreshing }),
        setProcessedElements: (elements: CountedHTMLElement[]) => ({ elements }),
        setElementsLoading: (loading: boolean) => ({ loading }),
        setProcessingProgress: (processed: number, total: number) => ({ processed, total }),
        startAreaSelection: true,
        cancelAreaSelection: true,
        setAreaHover: (anchor: HTMLElement, candidate: HTMLElement) => ({ anchor, candidate }),
        setAreaHoverCandidate: (candidate: HTMLElement) => ({ candidate }),
        stepAreaHover: (direction: 'up' | 'down') => ({ direction }),
        setAreaCandidates: (candidates: HTMLElement[]) => ({ candidates }),
        selectHeatmapAreaFilter: (element: HTMLElement | null) => ({ element }),
        setHeatmapAreaFilter: (element: HTMLElement | null, selector: string | null) => ({ element, selector }),
        // swap the tracked node for a re-resolved one without refetching: the selector is
        // unchanged, so the server response would be byte-identical
        rebindAreaElement: (element: HTMLElement) => ({ element }),
        updateAreaBounds: true,
    }),
    windowValues(() => ({
        windowWidth: (window: Window) => window.innerWidth,
        windowHeight: (window: Window) => window.innerHeight,
    })),
    reducers({
        matchLinksByHref: [false, { setMatchLinksByHref: (_, { matchLinksByHref }) => matchLinksByHref }],
        // exits picking mode only — an already-applied filter is cleared separately via
        // selectHeatmapAreaFilter(null) (the snack's close button)
        areaSelectionActive: [
            false,
            {
                startAreaSelection: () => true,
                cancelAreaSelection: () => false,
                setHeatmapAreaFilter: () => false,
            },
        ],
        // the raw element under the pointer; the fixed reference point arrow-key steps
        // shrink back toward
        areaHoverAnchor: [
            null as HTMLElement | null,
            {
                setAreaHover: (_, { anchor }) => anchor,
                startAreaSelection: () => null,
                cancelAreaSelection: () => null,
                setHeatmapAreaFilter: () => null,
            },
        ],
        // the currently highlighted candidate: the semantic snap of the anchor by default,
        // moved along the ancestor chain by arrow keys
        areaHoverElement: [
            null as HTMLElement | null,
            {
                setAreaHover: (_, { candidate }) => candidate,
                setAreaHoverCandidate: (_, { candidate }) => candidate,
                startAreaSelection: () => null,
                cancelAreaSelection: () => null,
                setHeatmapAreaFilter: () => null,
            },
        ],
        areaHoverStepped: [
            false,
            {
                setAreaHoverCandidate: () => true,
                setAreaHover: () => false,
                startAreaSelection: () => false,
                cancelAreaSelection: () => false,
                setHeatmapAreaFilter: () => false,
            },
        ],
        areaCandidates: [
            [] as HTMLElement[],
            {
                setAreaCandidates: (_, { candidates }) => candidates,
                cancelAreaSelection: () => [],
                setHeatmapAreaFilter: () => [],
            },
        ],
        // cleared on disableHeatmap and navigation via the listeners dispatching
        // setHeatmapAreaFilter(null, null), which also clears the pushed bounds
        heatmapAreaFilter: [
            null as { element: HTMLElement; selector: string | null } | null,
            {
                setHeatmapAreaFilter: (_, { element, selector }) => (element ? { element, selector } : null),
                rebindAreaElement: (state, { element }) => (state ? { ...state, element } : state),
            },
        ],
        lastElementStatsRequest: [
            null as { url: string | null; limit: number } | null,
            {
                getElementStats: (_, { url, limit }) => ({
                    url: url ?? null,
                    limit: limit ?? ELEMENT_STATS_PAGE_LIMIT,
                }),
            },
        ],
        canLoadMoreElementStats: [
            true,
            {
                getElementStatsSuccess: (_, { elementStats }) => elementStats.next !== null,
                getElementStatsFailure: () => true, // so at least someone can recover from transient errors
            },
        ],
        heatmapEnabled: [
            false,
            {
                enableHeatmap: () => true,
                disableHeatmap: () => false,
            },
        ],
        clickmapsEnabled: [
            true,
            {
                toggleClickmapsEnabled: (_, { enabled }) => enabled,
            },
        ],
        samplingFactor: [
            1,
            { persist: true },
            {
                setSamplingFactor: (_, { samplingFactor }) => samplingFactor,
            },
        ],
        elementMetrics: [
            new Map<HTMLElement, { visible: boolean }>(),
            {
                updateElementMetrics: (state, { observedElements }) => {
                    if (observedElements.length === 0) {
                        return state
                    }

                    const onUpdate = new Map(Array.from(state.entries()))
                    for (const [element, visible] of observedElements) {
                        onUpdate.set(element, { visible })
                    }

                    return onUpdate
                },
                toggleClickmapsEnabled: (state, { enabled }) => (enabled ? state : new Map()),
            },
        ],
        processedElements: [
            [] as CountedHTMLElement[],
            {
                setProcessedElements: (_, { elements }) => elements,
                toggleClickmapsEnabled: (state, { enabled }) => (enabled ? state : []),
                resetElementStats: () => [],
            },
        ],
        elementsLoading: [
            false,
            {
                setElementsLoading: (_, { loading }) => loading,
                processElements: () => true,
                setProcessedElements: () => false,
                toggleClickmapsEnabled: (state, { enabled }) => (enabled ? state : false),
            },
        ],
        processingProgress: [
            null as { processed: number; total: number } | null,
            {
                setProcessingProgress: (_, { processed, total }) => (processed >= total ? null : { processed, total }),
                setProcessedElements: () => null,
                toggleClickmapsEnabled: () => null,
            },
        ],
        isRefreshing: [
            false,
            {
                setIsRefreshing: (_, { isRefreshing }) => isRefreshing,
            },
        ],
    }),
    loaders(({ values }) => ({
        elementStats: [
            null as PaginatedResponse<ElementsEventType> | null,
            {
                resetElementStats: () => emptyElementsStatsPages,
                getElementStats: async ({ url, limit }, breakpoint) => {
                    await breakpoint(150)

                    // the gates can flip while we sit in the breakpoint (the embedded app sends
                    // toggleClickmapsEnabled(false) just after mount), so re-check before fetching
                    if (!values.heatmapEnabled || !values.clickmapsEnabled) {
                        return values.elementStats ?? emptyElementsStatsPages
                    }

                    const { href, wildcardHref } = values
                    // We re-raise below to drive getElementStatsFailure; let the global
                    // loader handler report it once rather than capturing twice.
                    const options = {
                        context: 'load_heatmap_stats',
                        reauthenticateOnForbidden: true,
                        captureOnError: false,
                    }
                    const result = url
                        ? // Paginating — the URL came from a previous response body.
                          await toolbarApi.elementStats.page(url, options)
                        : await toolbarApi.elementStats.list(
                              {
                                  properties: buildElementStatsProperties(
                                      href,
                                      wildcardHref,
                                      values.heatmapAreaFilter?.selector ?? null
                                  ),
                                  date_from: values.commonFilters.date_from,
                                  date_to: values.commonFilters.date_to,
                                  paginate_response: true,
                                  sampling_factor: values.samplingFactor,
                                  limit: limit ?? ELEMENT_STATS_PAGE_LIMIT,
                                  // the matchers only read the configured data attributes from each
                                  // element's attributes map, so let the server drop the rest
                                  data_attributes: values.wantedDataAttributes.join(','),
                              },
                              options
                          )
                    breakpoint()

                    if (result.status === 403) {
                        return emptyElementsStatsPages
                    }

                    if (!result.ok || !Array.isArray(result.data.results)) {
                        throw new Error('Error loading HeatMap data!')
                    }

                    return {
                        // if url is present we are paginating and merge results, otherwise we only use the new results
                        results: url
                            ? dedupeByChainIdentity([
                                  ...(values.elementStats?.results || []),
                                  ...(result.data.results || []),
                              ])
                            : result.data.results || [],
                        next: result.data.next,
                        previous: result.data.previous,
                    } as PaginatedResponse<ElementsEventType>
                },
            },
        ],
    })),
    selectors(() => ({
        countedElements: [
            (s) => [s.processedElements, s.elementMetrics],
            (processedElements, elementMetrics) => {
                return processedElements.map((el: CountedHTMLElement) => {
                    const metrics = elementMetrics.get(el.element)
                    return metrics ? { ...el, visible: metrics.visible } : el
                })
            },
        ],
        elementCount: [(s) => [s.countedElements], (countedElements) => countedElements.length],
        loadedElementStatsCount: [(s) => [s.elementStats], (elementStats) => elementStats?.results?.length ?? 0],
        // isTooSimple always reads attr__data-attr, so request it alongside the configured data
        // attributes — first, so it survives the server's entry cap however many are configured
        wantedDataAttributes: [
            () => [toolbarConfigLogic.selectors.dataAttributes],
            (dataAttributes: string[]): string[] => Array.from(new Set(['data-attr', ...dataAttributes])),
        ],
        clickCount: [
            (s) => [s.countedElements],
            (countedElements) => (countedElements ? countedElements.map((e) => e.count).reduce((a, b) => a + b, 0) : 0),
        ],
        highestClickCount: [
            (s) => [s.countedElements],
            (countedElements) =>
                countedElements ? countedElements.map((e) => e.count).reduce((a, b) => (b > a ? b : a), 0) : 0,
        ],

        scrollDepthPosthogJsError: [
            (s) => [s.posthog],
            (posthog: PostHog | null): 'version' | 'disabled' | null => {
                if (!posthog) {
                    return null
                }

                const posthogVersion =
                    posthog?.version ??
                    posthog?._calculate_event_properties('test', {}, new Date())?.['$lib_version'] ??
                    '0.0.0'

                if (!(posthog as any)?.scrollManager?.scrollY) {
                    return 'version'
                }

                const isSupported = doesVersionSupportScrollDepth(posthogVersion)
                const isDisabled = posthog?.config.disable_scroll_properties

                return !isSupported ? 'version' : isDisabled ? 'disabled' : null
            },
        ],
        processingInputs: [
            (s) => [
                s.elementStats,
                toolbarConfigLogic.selectors.dataAttributes,
                s.href,
                s.matchLinksByHref,
                s.clickmapsEnabled,
                s.heatmapAreaFilter,
            ],
            (elementStats, dataAttributes, href, matchLinksByHref, clickmapsEnabled, heatmapAreaFilter) => ({
                elementStats,
                dataAttributes,
                href,
                matchLinksByHref,
                clickmapsEnabled,
                heatmapAreaFilter,
            }),
        ],
    })),
    subscriptions(({ actions, values }) => {
        const updateAreaBoundsIfFiltered = (): void => {
            if (values.heatmapAreaFilter) {
                actions.updateAreaBounds()
            }
        }
        return {
            viewportRange: () => {
                actions.maybeLoadHeatmap()
            },
            windowWidth: updateAreaBoundsIfFiltered,
            windowHeight: updateAreaBoundsIfFiltered,
        }
    }),
    listeners(({ actions, values, cache }) => ({
        processElements: async ({ trigger }, breakpoint) => {
            const SLICE_BUDGET_MS = 10
            const startedAt = performance.now()

            const { elementStats, dataAttributes, href, matchLinksByHref, clickmapsEnabled, heatmapAreaFilter } =
                values.processingInputs

            if (!clickmapsEnabled || !elementStats?.results?.length) {
                actions.setProcessedElements([])
                actions.setIsRefreshing(false)
                return
            }

            // a re-render can replace the picked area node between mutation-observer ticks;
            // re-resolve so the containment check keeps filtering across the swap
            const areaElement = heatmapAreaFilter ? resolveAreaElement(heatmapAreaFilter) : null
            if (heatmapAreaFilter && !areaElement) {
                // unresolvable: hand off to the action that owns the clear-with-telemetry path
                // now, rather than showing unfiltered rows until the mutation observer's
                // debounce next fires (sustained DOM churn can push that back indefinitely)
                actions.updateAreaBounds()
            }

            cache.visibilityCache = cache.visibilityCache || new WeakMap<HTMLElement, boolean>()
            const cursorPointerCache = new WeakMap<HTMLElement, boolean>()
            const { pageElements, domIndex, hasShadowRoots, cacheHit } = getCachedPageElements(
                cache as ElementProcessingCache,
                href
            )
            const eventsToProcess = elementStats.results
            const totalEvents = eventsToProcess.length

            const matchedElementByIdentity = (cache as ElementProcessingCache).matchedElementByIdentity
            const allTrimmedElements: CountedHTMLElement[] = []
            let indexMatchedCount = 0
            let fallbackMatchedCount = 0
            let matchCacheHitCount = 0
            let completed = false
            let sliceStart = performance.now()

            try {
                for (let i = 0; i < totalEvents; i++) {
                    const event = eventsToProcess[i]
                    const identity = event.hash ? `${event.type}:${event.hash}` : null
                    const cachedElement = identity ? matchedElementByIdentity.get(identity) : undefined

                    let matched: CountedHTMLElement | null = null
                    if (cachedElement !== undefined) {
                        matchCacheHitCount += 1
                        matched = cachedElement
                            ? {
                                  element: cachedElement,
                                  count: event.count,
                                  selector: '',
                                  hash: event.hash,
                                  type: event.type,
                                  clickCount: 0,
                                  rageclickCount: 0,
                                  deadclickCount: 0,
                              }
                            : null
                    } else {
                        matched = matchEventToElementUsingIndex(event, dataAttributes, matchLinksByHref, domIndex)
                        if (matched) {
                            indexMatchedCount += 1
                        } else {
                            matched = matchEventToElementUsingSelectors(
                                event,
                                dataAttributes,
                                matchLinksByHref,
                                pageElements,
                                (cache as ElementProcessingCache).selectorToElements,
                                hasShadowRoots
                            )
                            if (matched) {
                                fallbackMatchedCount += 1
                            }
                        }
                        if (identity) {
                            matchedElementByIdentity.set(identity, matched?.element ?? null)
                        }
                    }

                    if (matched) {
                        const trimmed = trimElement(matched.element, { cursorPointerCache })
                        // the server already filters chains by the area selector, but chains can
                        // match DOM nodes outside the chosen area (stale markup, repeated
                        // components), so keep the display honest with a containment check —
                        // composed-tree containment, since matches can live inside shadow roots
                        const withinArea =
                            !areaElement || (trimmed !== null && containsInComposedTree(areaElement, trimmed))
                        if (
                            trimmed &&
                            withinArea &&
                            elementIsVisible(trimmed, cache.visibilityCache as WeakMap<HTMLElement, boolean>)
                        ) {
                            allTrimmedElements.push({ ...matched, element: trimmed })
                        }
                    }

                    if (performance.now() - sliceStart > SLICE_BUDGET_MS) {
                        actions.setProcessingProgress(i + 1, totalEvents)
                        await yieldToMain()
                        breakpoint()
                        sliceStart = performance.now()
                    }
                }

                breakpoint()
                actions.setProcessedElements(aggregateAndSortElements(allTrimmedElements))
                actions.startElementObservation()
                actions.setIsRefreshing(false)
                completed = true
            } finally {
                // fire on cancelled runs too — the slow pages that get superseded are exactly
                // the ones we most need to see
                toolbarPosthogJS.capture('toolbar clickmap processed', {
                    event_count: totalEvents,
                    matched_element_count: allTrimmedElements.length,
                    index_matched_count: indexMatchedCount,
                    fallback_matched_count: fallbackMatchedCount,
                    match_cache_hit_count: matchCacheHitCount,
                    page_element_count: pageElements.length,
                    has_shadow_roots: hasShadowRoots,
                    duration_ms: Math.round(performance.now() - startedAt),
                    trigger,
                    cache_hit: cacheHit,
                    completed,
                })
            }
        },

        enableHeatmap: () => {
            actions.setDataHref(values.href)
            actions.loadAllEnabled()
            toolbarPosthogJS.capture('toolbar mode triggered', { mode: 'heatmap', enabled: true })
        },

        disableHeatmap: () => {
            actions.resetElementStats()
            actions.resetHeatmapData()
            if (values.areaSelectionActive) {
                actions.cancelAreaSelection()
            }
            // route the clear through the one action whose listener owns the
            // "filter null => pushed bounds null" invariant
            if (values.heatmapAreaFilter) {
                actions.setHeatmapAreaFilter(null, null)
            }
            toolbarPosthogJS.capture('toolbar mode triggered', { mode: 'heatmap', enabled: false })
        },

        // the feature flag gates only the menu button; the whole selection machine stays
        // dormant because startAreaSelection is that button's only caller — a second caller
        // would silently un-gate the feature
        startAreaSelection: () => {
            // product tours' picker also listens for document clicks; two armed pickers
            // would both consume the same page click
            const productTours = productToursLogic.findMounted()
            if (productTours?.values.isSelecting) {
                productTours.actions.setEditorState({ mode: 'idle' })
            }
            const candidates = computeAreaCandidates()
            actions.setAreaCandidates(candidates)
            toolbarPosthogJS.capture('toolbar heatmap area selection started', {
                candidate_count: candidates.length,
                capped: candidates.length === AREA_CANDIDATE_LIMIT,
            })
        },

        stepAreaHover: ({ direction }) => {
            const { areaHoverAnchor, areaHoverElement } = values
            if (!areaHoverAnchor || !areaHoverElement) {
                return
            }
            const next = stepAreaCandidate(areaHoverAnchor, areaHoverElement, direction)
            if (next !== areaHoverElement) {
                actions.setAreaHoverCandidate(next)
            }
        },

        selectHeatmapAreaFilter: ({ element }) => {
            const selector = element
                ? elementToActionStep(element, toolbarConfigLogic.values.dataAttributes).selector || null
                : null
            const arrowStepped = values.areaHoverStepped
            actions.setHeatmapAreaFilter(element, selector)
            toolbarPosthogJS.capture('toolbar heatmap area filter changed', {
                enabled: !!element,
                has_selector: !!selector,
                tag_name: element?.tagName.toLowerCase() ?? null,
                trigger: 'user',
                arrow_stepped: arrowStepped,
            })
        },

        setHeatmapAreaFilter: ({ element }) => {
            if (element) {
                actions.updateAreaBounds()
            } else {
                actions.setHeatmapBoundsFilter(null)
            }
            // apply the containment check to the already-loaded stats immediately so the
            // selection feels instant, then fetch the server-filtered data
            actions.processElements('toggle')
            actions.maybeLoadClickmap()
        },

        rebindAreaElement: () => {
            actions.updateAreaBounds()
        },

        updateAreaBounds: () => {
            const filter = values.heatmapAreaFilter
            if (!filter) {
                return
            }
            const resolved = resolveAreaElement(filter)
            if (!resolved) {
                // the node is gone and the selector no longer matches anything; clear the
                // filter visibly rather than degrade silently
                actions.setHeatmapAreaFilter(null, null)
                toolbarPosthogJS.capture('toolbar heatmap area filter changed', {
                    enabled: false,
                    has_selector: !!filter.selector,
                    tag_name: filter.element.tagName.toLowerCase(),
                    trigger: 'element_lost',
                })
                return
            }
            if (resolved !== filter.element) {
                // a re-render replaced the node; follow it via the stored selector
                actions.rebindAreaElement(resolved)
                return
            }
            actions.setHeatmapBoundsFilter(computeAreaBounds(filter.element))
        },

        startElementObservation: () => {
            if (!cache.intersectionObserver || !values.clickmapsEnabled) {
                return
            }

            const countedElements = values.countedElements
            cache.intersectionObserver.disconnect()
            cache.intersectionObserver.observe(document.body)
            countedElements.forEach((element) => {
                cache.intersectionObserver.observe(element.element)
            })
        },

        stopElementObservation: () => {
            cache.intersectionObserver?.disconnect()
        },

        loadAllEnabled: async () => {
            actions.maybeLoadHeatmap()
            actions.maybeLoadClickmap()
        },

        maybeLoadClickmap: async () => {
            // this logic stays mounted while the heatmap menu is closed, so navigation
            // must not fetch stats until the user is actually looking
            if (values.heatmapEnabled && values.clickmapsEnabled) {
                actions.getElementStats()
            }
        },

        maybeLoadHeatmap: async () => {
            if (values.heatmapEnabled && values.heatmapFilters.enabled && values.heatmapFilters.type) {
                actions.loadHeatmap()
            }
        },

        setHref: ({ href }) => {
            if (values.heatmapEnabled) {
                actions.setHrefMatchType(href === window.location.href ? 'exact' : 'pattern')
                actions.setDataHref(href)
            }
            // the area filter describes an element on the page it was picked on; carrying it
            // across navigation would filter the new page by the old page's selector and bounds
            if (values.areaSelectionActive) {
                actions.cancelAreaSelection()
            }
            if (values.heatmapAreaFilter) {
                actions.setHeatmapAreaFilter(null, null)
            }
            actions.maybeLoadClickmap()
        },

        setWildcardHref: ({ href }) => {
            if (values.heatmapEnabled) {
                actions.setHrefMatchType(href === window.location.href ? 'exact' : 'pattern')
                actions.setDataHref(href)
            }
            actions.maybeLoadClickmap()
        },
        setCommonFilters: () => {
            actions.loadAllEnabled()
        },
        setSamplingFactor: () => {
            actions.maybeLoadClickmap()
        },

        toggleClickmapsEnabled: () => {
            if (values.clickmapsEnabled) {
                actions.maybeLoadClickmap()
            } else {
                actions.stopElementObservation()
                actions.resetElementStats()
                cache.pageElements = undefined
                cache.selectorToElements = new Map()
                cache.matchedElementByIdentity = new Map()
                cache.lastHref = undefined
                cache.visibilityCache = new WeakMap()
            }
        },

        loadMoreElementStats: () => {
            if (values.elementStats?.next) {
                actions.getElementStats(values.elementStats.next)
            } else if (!values.elementStats) {
                // the initial load failed, so the button doubles as the retry affordance
                actions.maybeLoadClickmap()
            }
        },

        getElementStatsSuccess: ({ elementStats }) => {
            const request = values.lastElementStatsRequest
            const trigger: ClickmapProcessingTrigger = request?.url
                ? 'pagination'
                : request?.limit === ELEMENT_STATS_AUTO_LOAD_LIMIT
                  ? 'auto-load'
                  : 'initial'
            actions.processElements(trigger)

            // the first page painted; fetch the rest in one background request. Only the initial
            // trigger refetches, so an auto-load result can never re-trigger itself.
            if (trigger === 'initial' && elementStats?.next && values.heatmapEnabled && values.clickmapsEnabled) {
                actions.getElementStats(null, ELEMENT_STATS_AUTO_LOAD_LIMIT)
            }
        },

        setMatchLinksByHref: () => {
            // href matching changes what a row matches, so cached matches are stale
            ;(cache as ElementProcessingCache).matchedElementByIdentity = new Map()
            actions.processElements('toggle')
        },

        refreshClickmap: () => {
            if (!values.clickmapsEnabled) {
                return
            }
            actions.setIsRefreshing(true)
            invalidatePageElementsCache(cache as ElementProcessingCache)
            actions.processElements('refresh')
        },

        patchHeatmapFilters: ({ filters }) => {
            if (filters.type) {
                actions.resetHeatmapData()
            }
            actions.maybeLoadHeatmap()
        },
    })),
    afterMount(({ actions, cache, values }) => {
        cache.selectorToElements = new Map()
        cache.matchedElementByIdentity = new Map()
        cache.visibilityCache = new WeakMap()

        cache.disposables.add(() => {
            const intersectionObserver = new IntersectionObserver((entries) => {
                const observedElements: [HTMLElement, boolean][] = []
                entries.forEach((entry) => {
                    const element = entry.target as HTMLElement
                    observedElements.push([element, entry.isIntersecting])
                })
                actions.updateElementMetrics(observedElements)
            })

            cache.intersectionObserver = intersectionObserver

            return () => intersectionObserver.disconnect()
        }, 'intersectionObserver')

        cache.disposables.add(() => {
            let debounceTimer: ReturnType<typeof setTimeout> | null = null

            const mutationObserver = new MutationObserver(() => {
                if (debounceTimer) {
                    clearTimeout(debounceTimer)
                }
                debounceTimer = setTimeout(() => {
                    invalidatePageElementsCache(cache as ElementProcessingCache)
                    invalidateZoomCache()
                    // mid-pick DOM churn would leave the candidate boxes pointing at stale nodes
                    if (values.areaSelectionActive) {
                        actions.setAreaCandidates(computeAreaCandidates())
                    }
                    // layout shifts move the filtered area; this also re-resolves or clears
                    // the filter when the picked node was replaced by a re-render
                    if (values.heatmapAreaFilter) {
                        actions.updateAreaBounds()
                    }
                    debounceTimer = null
                }, 500)
            })

            mutationObserver.observe(document.body, {
                childList: true,
                subtree: true,
            })

            cache.mutationObserver = mutationObserver

            return () => {
                if (debounceTimer) {
                    clearTimeout(debounceTimer)
                }
                mutationObserver.disconnect()
            }
        }, 'mutationObserver')

        cache.disposables.add(() => {
            // capture-phase document listeners so area picking sees page elements before the
            // page's own handlers do; guarded by areaSelectionActive so they cost nothing otherwise
            const isToolbarElement = (element: HTMLElement): boolean =>
                getToolbarRootElement()?.contains(element) ?? false

            const onMouseOver = (e: MouseEvent): void => {
                if (!values.areaSelectionActive) {
                    return
                }
                const target = e.target as HTMLElement | null
                if (!target || isToolbarElement(target)) {
                    return
                }
                // moving the mouse resets any arrow-key refinement to the new hover's snap
                actions.setAreaHover(target, resolveAreaTarget(target))
            }

            const onClick = (e: MouseEvent): void => {
                if (!values.areaSelectionActive) {
                    return
                }
                const target = e.target as HTMLElement | null
                if (!target || isToolbarElement(target)) {
                    return
                }
                e.preventDefault()
                e.stopPropagation()
                // the highlighted candidate, not the click target: arrow keys may have
                // grown or shrunk the selection away from what's under the pointer
                actions.selectHeatmapAreaFilter(values.areaHoverElement ?? resolveAreaTarget(target))
            }

            const onKeyDown = (e: KeyboardEvent): void => {
                if (!values.areaSelectionActive || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) {
                    return
                }
                // focus usually sits on the toolbar button that started the pick, and shadow
                // retargeting turns document-level targets into the toolbar host, so a
                // toolbar-membership guard would eat every arrow key; guard on the composed
                // target being editable instead — arrows step the highlight unless typing
                const composedTarget = e.composedPath()[0]
                if (
                    composedTarget instanceof HTMLElement &&
                    composedTarget.closest('input, textarea, select, [contenteditable]')
                ) {
                    return
                }
                // arrows refine the selection, so they must not scroll the page mid-pick
                e.preventDefault()
                e.stopPropagation()
                actions.stepAreaHover(e.key === 'ArrowUp' ? 'up' : 'down')
            }

            document.addEventListener('mouseover', onMouseOver, true)
            document.addEventListener('click', onClick, true)
            document.addEventListener('keydown', onKeyDown, true)
            return () => {
                document.removeEventListener('mouseover', onMouseOver, true)
                document.removeEventListener('click', onClick, true)
                document.removeEventListener('keydown', onKeyDown, true)
            }
        }, 'areaSelectionListeners')

        cache.disposables.add(() => {
            const handleVisibilityChange = (): void => {
                if (document.hidden) {
                    actions.stopElementObservation()
                } else {
                    if (values.clickmapsEnabled) {
                        actions.startElementObservation()
                    }
                }
            }

            document.addEventListener('visibilitychange', handleVisibilityChange)
            return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
        }, 'visibilityChangeHandler')
    }),
    beforeUnmount(({ cache }) => {
        // heatmapDataLogic outlives this logic, so reducer resets alone can't clear the bounds
        heatmapDataLogic.findMounted({ context: 'toolbar' })?.actions.setHeatmapBoundsFilter(null)
        cache.pageElements = undefined
        cache.selectorToElements = new Map()
        cache.matchedElementByIdentity = new Map()
        cache.visibilityCache = new WeakMap()
        cache.lastHref = undefined
        cache.cacheInvalidated = false
    }),
])

export function dedupeByChainIdentity(events: ElementsEventType[]): ElementsEventType[] {
    const seen = new Set<string>()
    const deduped: ElementsEventType[] = []
    for (const event of events) {
        // the server hashes the raw chain before attribute filtering, so distinct chains that
        // serialize identically after trimming stay distinct; the serialized-content fallback is
        // transitional for servers that still return hash as null — delete once that's none of them
        const identity = `${event.type}:${event.hash ?? JSON.stringify(event.elements)}`
        if (seen.has(identity)) {
            continue
        }
        seen.add(identity)
        deduped.push(event)
    }
    return deduped
}

function aggregateAndSortElements(elements: CountedHTMLElement[]): CountedHTMLElement[] {
    const normalisedElements = new Map<HTMLElement, CountedHTMLElement>()

    for (const countedElement of elements) {
        if (normalisedElements.has(countedElement.element)) {
            const existing = normalisedElements.get(countedElement.element)!
            existing.count += countedElement.count
            existing.clickCount += countedElement.type === '$autocapture' ? countedElement.count : 0
            existing.rageclickCount += countedElement.type === '$rageclick' ? countedElement.count : 0
            existing.deadclickCount += countedElement.type === '$dead_click' ? countedElement.count : 0
        } else {
            normalisedElements.set(countedElement.element, {
                ...countedElement,
                clickCount: countedElement.type === '$autocapture' ? countedElement.count : 0,
                rageclickCount: countedElement.type === '$rageclick' ? countedElement.count : 0,
                deadclickCount: countedElement.type === '$dead_click' ? countedElement.count : 0,
            })
        }
    }

    const sorted = Array.from(normalisedElements.values())
    sorted.sort((a, b) => b.count - a.count)

    return sorted.map((e, i) => ({ ...e, position: i + 1 }))
}

export const escapeUnescapedRegex = (str: string): string =>
    str.replace(/\\.|([.*+?^=!:${}()|[\]/\\])/g, (match, group1) => (group1 ? `\\${group1}` : match))
