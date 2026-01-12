import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { encodeParams } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import { windowValues } from 'kea-window-values'
import { PostHog } from 'posthog-js'
import { collectAllElementsDeep, querySelectorAllDeep } from 'query-selector-shadow-dom'

import { elementToSelector } from 'lib/actionUtils'
import { PaginatedResponse } from 'lib/api'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { createVersionChecker } from 'lib/utils/semver'

import { buildDOMIndex, matchEventToElementUsingIndex } from '~/toolbar/elements/domElementIndex'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { CountedHTMLElement, ElementsEventType } from '~/toolbar/types'
import { elementIsVisible, trimElement } from '~/toolbar/utils'
import { FilterType, PropertyFilterType, PropertyOperator } from '~/types'

import type { heatmapToolbarMenuLogicType } from './heatmapToolbarMenuLogicType'

export const doesVersionSupportScrollDepth = createVersionChecker('1.99')

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

interface ElementProcessingCache {
    pageElements?: HTMLElement[]
    selectorToElements: Record<string, HTMLElement[]>
    lastHref?: string
    intersectionObserver?: IntersectionObserver
    visibilityCache: WeakMap<HTMLElement, boolean>
    mutationObserver?: MutationObserver
    cacheInvalidated?: boolean
}

function invalidatePageElementsCache(cache: ElementProcessingCache): void {
    cache.cacheInvalidated = true
    cache.visibilityCache = new WeakMap()
}

function getCachedPageElements(cache: ElementProcessingCache, href: string): HTMLElement[] {
    const hrefChanged = cache.lastHref !== href
    const cacheValid = cache.pageElements && !hrefChanged && !cache.cacheInvalidated

    if (cacheValid && cache.pageElements) {
        return cache.pageElements
    }

    cache.pageElements = collectAllElementsDeep('*', document)
    cache.lastHref = href
    cache.selectorToElements = {}
    cache.cacheInvalidated = false
    return cache.pageElements
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
                'heatmapScrollY',
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
                'setHeatmapScrollY',
            ],
        ],
    })),
    actions({
        getElementStats: (url?: string | null) => ({
            url,
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
        startScrollTracking: true,
        stopScrollTracking: true,
        startElementObservation: true,
        stopElementObservation: true,
        processElements: true,
        refreshClickmap: true,
        setIsRefreshing: (isRefreshing: boolean) => ({ isRefreshing }),
        setProcessedElements: (elements: CountedHTMLElement[]) => ({ elements }),
        setElementsLoading: (loading: boolean) => ({ loading }),
        setProcessingProgress: (processed: number, total: number) => ({ processed, total }),
        setClickmapContainerSelector: (selector: string | null) => ({ selector }),
        setPickingClickmapContainer: (picking: boolean) => ({ picking }),
        pickClickmapContainer: (element: HTMLElement) => ({ element }),
    }),
    windowValues(() => ({
        windowWidth: (window: Window) => window.innerWidth,
        windowHeight: (window: Window) => window.innerHeight,
    })),
    reducers({
        matchLinksByHref: [false, { setMatchLinksByHref: (_, { matchLinksByHref }) => matchLinksByHref }],
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
                getElementStatsFailure: () => false,
            },
        ],
        clickmapsEnabled: [
            false,
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
        clickmapContainerSelector: [
            null as string | null,
            {
                setClickmapContainerSelector: (_, { selector }) => selector,
                toggleClickmapsEnabled: (state, { enabled }) => (enabled ? state : null),
            },
        ],
        pickingClickmapContainer: [
            false,
            {
                setPickingClickmapContainer: (_, { picking }) => picking,
                pickClickmapContainer: () => false,
                toggleClickmapsEnabled: () => false,
            },
        ],
    }),
    loaders(({ values }) => ({
        elementStats: [
            null as PaginatedResponse<ElementsEventType> | null,
            {
                resetElementStats: () => emptyElementsStatsPages,
                getElementStats: async ({ url }, breakpoint) => {
                    await breakpoint(150)

                    const { href, wildcardHref } = values
                    let defaultUrl: string = ''
                    if (!url) {
                        const params: Partial<FilterType> = {
                            properties: [
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
                            ],
                            date_from: values.commonFilters.date_from,
                            date_to: values.commonFilters.date_to,
                        }

                        defaultUrl = `/api/element/stats/${encodeParams(
                            { ...params, paginate_response: true, sampling_factor: values.samplingFactor },
                            '?'
                        )}`
                    }

                    // toolbar fetch collapses queryparams but this URL has multiple with the same name
                    const response = await toolbarFetch(
                        url || defaultUrl,
                        'GET',
                        undefined,
                        url ? 'use-as-provided' : 'full'
                    )
                    breakpoint()

                    if (response.status === 403) {
                        toolbarConfigLogic.actions.authenticate()
                        return emptyElementsStatsPages
                    }

                    const paginatedResults = await response.json()

                    if (!Array.isArray(paginatedResults.results)) {
                        throw new Error('Error loading HeatMap data!')
                    }

                    return {
                        results: [
                            // if url is present we are paginating and merge results, otherwise we only use the new results
                            ...(url ? values.elementStats?.results || [] : []),
                            ...(paginatedResults.results || []),
                        ],
                        next: paginatedResults.next,
                        previous: paginatedResults.previous,
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
                s.clickmapContainerSelector,
            ],
            (elementStats, dataAttributes, href, matchLinksByHref, clickmapsEnabled, clickmapContainerSelector) => ({
                elementStats,
                dataAttributes,
                href,
                matchLinksByHref,
                clickmapsEnabled,
                clickmapContainerSelector,
            }),
        ],
    })),
    subscriptions(({ actions }) => ({
        viewportRange: () => {
            actions.maybeLoadHeatmap()
        },
        countedElements: () => {
            actions.startElementObservation()
        },
    })),
    listeners(({ actions, values, cache }) => ({
        processElements: async (_, breakpoint) => {
            const BATCH_SIZE = 200
            const INITIAL_BATCH_SIZE = 50

            const { elementStats, dataAttributes, href, matchLinksByHref, clickmapsEnabled, clickmapContainerSelector } =
                values.processingInputs

            if (!clickmapsEnabled || !elementStats?.results?.length) {
                actions.setProcessedElements([])
                actions.setIsRefreshing(false)
                return
            }

            cache.visibilityCache = cache.visibilityCache || new WeakMap<HTMLElement, boolean>()
            const pageElements = getCachedPageElements(cache as ElementProcessingCache, href)
            const domIndex = buildDOMIndex(pageElements)
            const eventsToProcess = elementStats.results
            const totalEvents = eventsToProcess.length

            // Resolve container element if selector is set
            let containerElement: HTMLElement | null = null
            if (clickmapContainerSelector) {
                try {
                    containerElement = document.querySelector(clickmapContainerSelector) as HTMLElement | null
                } catch {
                    // Invalid selector, ignore
                }
            }

            const allTrimmedElements: CountedHTMLElement[] = []
            let processedCount = 0

            while (processedCount < totalEvents) {
                const batchSize = processedCount === 0 ? INITIAL_BATCH_SIZE : BATCH_SIZE
                const batchEnd = Math.min(processedCount + batchSize, totalEvents)

                for (let i = processedCount; i < batchEnd; i++) {
                    const event = eventsToProcess[i]
                    const matched =
                        matchEventToElementUsingIndex(event, dataAttributes, matchLinksByHref, domIndex) ||
                        matchEventToElement(
                            event,
                            dataAttributes,
                            matchLinksByHref,
                            pageElements,
                            cache as ElementProcessingCache
                        )

                    if (matched) {
                        const trimmed = trimElement(matched.element)
                        if (
                            trimmed &&
                            elementIsVisible(trimmed, cache.visibilityCache as WeakMap<HTMLElement, boolean>)
                        ) {
                            // Filter by container if set
                            if (containerElement && !containerElement.contains(trimmed)) {
                                continue
                            }
                            allTrimmedElements.push({ ...matched, element: trimmed })
                        }
                    }
                }

                processedCount = batchEnd
                actions.setProcessedElements(aggregateAndSortElements(allTrimmedElements))
                actions.setProcessingProgress(processedCount, totalEvents)

                breakpoint()
                await yieldToMain()
            }

            actions.setIsRefreshing(false)
        },

        enableHeatmap: () => {
            actions.setDataHref(values.href)
            actions.loadAllEnabled()
            actions.startScrollTracking()
            toolbarPosthogJS.capture('toolbar mode triggered', { mode: 'heatmap', enabled: true })
        },

        disableHeatmap: () => {
            actions.stopScrollTracking()
            actions.resetElementStats()
            actions.resetHeatmapData()
            toolbarPosthogJS.capture('toolbar mode triggered', { mode: 'heatmap', enabled: false })
        },

        startScrollTracking: () => {
            cache.disposables.add(() => {
                const timerId = setInterval(() => {
                    const scrollY = values.posthog?.scrollManager?.scrollY() ?? 0
                    if (values.heatmapScrollY !== scrollY) {
                        actions.setHeatmapScrollY(scrollY)
                    }
                }, 50)
                return () => clearInterval(timerId)
            }, 'scrollCheckTimer')
        },

        stopScrollTracking: () => {
            cache.disposables.dispose('scrollCheckTimer')
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
            if (values.clickmapsEnabled) {
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
                actions.getElementStats()
            } else {
                actions.stopElementObservation()
                actions.resetElementStats()
                cache.pageElements = undefined
                cache.selectorToElements = {}
                cache.lastHref = undefined
                cache.visibilityCache = new WeakMap()
            }
        },

        loadMoreElementStats: () => {
            if (values.elementStats?.next) {
                actions.getElementStats(values.elementStats.next)
            }
        },

        getElementStatsSuccess: () => {
            actions.processElements()
        },

        setMatchLinksByHref: () => {
            actions.processElements()
        },

        setClickmapContainerSelector: () => {
            actions.processElements()
        },

        pickClickmapContainer: ({ element }) => {
            const selector = elementToSelector(element, toolbarConfigLogic.values.dataAttributes)
            if (selector) {
                actions.setClickmapContainerSelector(selector)
            }
        },

        refreshClickmap: () => {
            if (!values.clickmapsEnabled) {
                return
            }
            actions.setIsRefreshing(true)
            invalidatePageElementsCache(cache as ElementProcessingCache)
            actions.processElements()
        },

        patchHeatmapFilters: ({ filters }) => {
            if (filters.type) {
                actions.resetHeatmapData()
            }
            actions.maybeLoadHeatmap()
        },
    })),
    afterMount(({ actions, cache, values }) => {
        cache.selectorToElements = {}
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
            const handleVisibilityChange = (): void => {
                if (document.hidden) {
                    actions.stopScrollTracking()
                    actions.stopElementObservation()
                } else {
                    if (values.heatmapEnabled) {
                        actions.startScrollTracking()
                    }
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
        cache.pageElements = undefined
        cache.selectorToElements = {}
        cache.visibilityCache = new WeakMap()
        cache.lastHref = undefined
        cache.cacheInvalidated = false
    }),
])

function matchEventToElement(
    event: ElementsEventType,
    dataAttributes: string[],
    matchLinksByHref: boolean,
    pageElements: HTMLElement[],
    cache: ElementProcessingCache
): CountedHTMLElement | null {
    let lastSelector: string | undefined

    for (let i = 0; i < event.elements.length; i++) {
        const element = event.elements[i]
        const selector =
            elementToSelector(matchLinksByHref ? element : { ...element, href: undefined }, dataAttributes) || '*'
        const combinedSelector = lastSelector ? `${selector} > ${lastSelector}` : selector

        try {
            let domElements: HTMLElement[] | undefined = cache.selectorToElements[combinedSelector]
            if (domElements === undefined) {
                domElements = Array.from(querySelectorAllDeep(combinedSelector, document, pageElements))
                cache.selectorToElements[combinedSelector] = domElements
            }

            if (domElements.length === 1) {
                const e = event.elements[i]
                const isTooSimple =
                    i === 0 &&
                    e.tag_name &&
                    !e.attr_class &&
                    !e.attr_id &&
                    !e.href &&
                    !e.text &&
                    e.nth_child === 1 &&
                    e.nth_of_type === 1 &&
                    !e.attributes['attr__data-attr']

                if (!isTooSimple) {
                    return {
                        element: domElements[0],
                        count: event.count,
                        selector: selector,
                        hash: event.hash,
                        type: event.type,
                    } as CountedHTMLElement
                }
            }

            if (domElements.length === 0) {
                if (i === event.elements.length - 1) {
                    return null
                } else if (i > 0 && lastSelector) {
                    lastSelector = `* > ${lastSelector}`
                    continue
                }
            }
        } catch {
            break
        }

        lastSelector = combinedSelector
    }

    return null
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
