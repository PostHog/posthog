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

import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { CountedHTMLElement, ElementsEventType } from '~/toolbar/types'
import { elementToActionStep, trimElement } from '~/toolbar/utils'
import { FilterType, PropertyFilterType, PropertyOperator } from '~/types'

import type { heatmapToolbarMenuLogicType } from './heatmapToolbarMenuLogicType'

export const doesVersionSupportScrollDepth = createVersionChecker('1.99')

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
    selectors(({ cache }) => ({
        elements: [
            (s) => [
                s.elementStats,
                toolbarConfigLogic.selectors.dataAttributes,
                s.href,
                s.matchLinksByHref,
                s.clickmapsEnabled,
            ],
            (elementStats, dataAttributes, href, matchLinksByHref, clickmapsEnabled) => {
                if (!clickmapsEnabled) {
                    return []
                }

                cache.pageElements = cache.lastHref == href ? cache.pageElements : collectAllElementsDeep('*', document)
                cache.selectorToElements = cache.lastHref == href ? cache.selectorToElements : {}

                cache.lastHref = href

                const elements: CountedHTMLElement[] = []
                elementStats?.results.forEach((event) => {
                    let combinedSelector: string
                    let lastSelector: string | undefined
                    for (let i = 0; i < event.elements.length; i++) {
                        const element = event.elements[i]
                        const selector =
                            elementToSelector(
                                matchLinksByHref ? element : { ...element, href: undefined },
                                dataAttributes
                            ) || '*'
                        combinedSelector = lastSelector ? `${selector} > ${lastSelector}` : selector

                        try {
                            let domElements: HTMLElement[] | undefined = cache.selectorToElements?.[combinedSelector]
                            if (domElements === undefined) {
                                domElements = Array.from(
                                    querySelectorAllDeep(combinedSelector, document, cache.pageElements)
                                )
                                cache.selectorToElements[combinedSelector] = domElements
                            }

                            if (domElements.length === 1) {
                                const e = event.elements[i]

                                // element like "svg" (only tag, no class/id/etc.) as the first one
                                if (
                                    i === 0 &&
                                    e.tag_name &&
                                    !e.attr_class &&
                                    !e.attr_id &&
                                    !e.href &&
                                    !e.text &&
                                    e.nth_child === 1 &&
                                    e.nth_of_type === 1 &&
                                    !e.attributes['attr__data-attr']
                                ) {
                                    // too simple selector, bail
                                } else {
                                    elements.push({
                                        element: domElements[0],
                                        count: event.count,
                                        selector: selector,
                                        hash: event.hash,
                                        type: event.type,
                                    } as CountedHTMLElement)
                                    return null
                                }
                            }

                            if (domElements.length === 0) {
                                if (i === event.elements.length - 1) {
                                    return null
                                } else if (i > 0 && lastSelector) {
                                    // We already have something, but found nothing when adding the next selector.
                                    // Skip it and try with the next one...
                                    lastSelector = lastSelector ? `* > ${lastSelector}` : '*'
                                    continue
                                }
                            }
                        } catch {
                            break
                        }

                        lastSelector = combinedSelector

                        // TODO: what if multiple elements will continue to match until the end?
                    }
                })

                return elements
            },
        ],
        countedElements: [
            (s) => [s.elements, toolbarConfigLogic.selectors.dataAttributes, s.clickmapsEnabled, s.elementMetrics],
            (elements, dataAttributes, clickmapsEnabled, elementMetrics) => {
                if (!clickmapsEnabled || !cache.intersectionObserver) {
                    return []
                }

                const normalisedElements = new Map<HTMLElement, CountedHTMLElement>()

                for (const countedElement of elements || []) {
                    const trimmedElement = trimElement(countedElement.element)
                    if (!trimmedElement) {
                        continue
                    }

                    const metrics = elementMetrics.get(trimmedElement) || {
                        visible: isElementVisible(trimmedElement),
                        rect: trimmedElement.getBoundingClientRect(),
                    }

                    if (normalisedElements.has(trimmedElement)) {
                        const existing = normalisedElements.get(trimmedElement)
                        if (existing) {
                            existing.count += countedElement.count
                            existing.clickCount += countedElement.type === '$autocapture' ? countedElement.count : 0
                            existing.rageclickCount += countedElement.type === '$rageclick' ? countedElement.count : 0
                            existing.deadclickCount += countedElement.type === '$dead_click' ? countedElement.count : 0
                            existing.visible = metrics.visible
                        }
                    } else {
                        normalisedElements.set(trimmedElement, {
                            ...countedElement,
                            clickCount: countedElement.type === '$autocapture' ? countedElement.count : 0,
                            rageclickCount: countedElement.type === '$rageclick' ? countedElement.count : 0,
                            deadclickCount: countedElement.type === '$dead_click' ? countedElement.count : 0,
                            element: trimmedElement,
                            actionStep: elementToActionStep(trimmedElement, dataAttributes),
                            visible: metrics.visible,
                        })
                    }
                }

                const countedElements = Array.from(normalisedElements.values())
                countedElements.sort((a, b) => b.count - a.count)

                return countedElements.map((e, i) => ({ ...e, position: i + 1 }))
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
            actions.setHref(href)
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
            }
        },

        loadMoreElementStats: () => {
            if (values.elementStats?.next) {
                actions.getElementStats(values.elementStats.next)
            }
        },

        patchHeatmapFilters: ({ filters }) => {
            if (filters.type) {
                // Clear the heatmap if the type changes
                actions.resetHeatmapData()
            }
            actions.maybeLoadHeatmap()
        },
    })),
    afterMount(({ actions, cache, values }) => {
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
    beforeUnmount(() => {
        // Disposables plugin handles cleanup automatically
    }),
])

function isElementVisible(element: HTMLElement): boolean {
    const style = window.getComputedStyle(element)
    return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0'
}

export const escapeUnescapedRegex = (str: string): string =>
    str.replace(/\\.|([.*+?^=!:${}()|[\]/\\])/g, (match, group1) => (group1 ? `\\${group1}` : match))
