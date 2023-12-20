import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { encodeParams } from 'kea-router'
import { elementToSelector, escapeRegex } from 'lib/actionUtils'
import { PaginatedResponse } from 'lib/api'
import { dateFilterToText } from 'lib/utils'
import { collectAllElementsDeep, querySelectorAllDeep } from 'query-selector-shadow-dom'

import { posthog } from '~/toolbar/posthog'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { CountedHTMLElement, ElementsEventType } from '~/toolbar/types'
import { elementToActionStep, trimElement } from '~/toolbar/utils'
import { FilterType, PropertyFilterType, PropertyOperator } from '~/types'

import type { heatmapLogicType } from './heatmapLogicType'

const emptyElementsStatsPages: PaginatedResponse<ElementsEventType> = {
    next: undefined,
    previous: undefined,
    results: [],
}

export const heatmapLogic = kea<heatmapLogicType>([
    path(['toolbar', 'elements', 'heatmapLogic']),
    connect({
        values: [toolbarConfigLogic, ['apiURL'], currentPageLogic, ['href', 'wildcardHref']],
        actions: [currentPageLogic, ['setHref', 'setWildcardHref']],
    }),
    actions({
        getElementStats: (url?: string | null) => ({
            url,
        }),
        enableHeatmap: true,
        disableHeatmap: true,
        setShowHeatmapTooltip: (showHeatmapTooltip: boolean) => ({ showHeatmapTooltip }),
        setShiftPressed: (shiftPressed: boolean) => ({ shiftPressed }),
        setHeatmapFilter: (filter: Partial<FilterType>) => ({ filter }),
        loadMoreElementStats: true,
        setMatchLinksByHref: (matchLinksByHref: boolean) => ({ matchLinksByHref }),
    }),
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
        heatmapLoading: [
            false,
            {
                getElementStats: () => true,
                getElementStatsSuccess: () => false,
                getElementStatsFailure: () => false,
                resetElementStats: () => false,
            },
        ],
        showHeatmapTooltip: [
            false,
            {
                setShowHeatmapTooltip: (_, { showHeatmapTooltip }) => showHeatmapTooltip,
            },
        ],
        shiftPressed: [
            false,
            {
                setShiftPressed: (_, { shiftPressed }) => shiftPressed,
            },
        ],
        heatmapFilter: [
            {} as Partial<FilterType>,
            {
                setHeatmapFilter: (_, { filter }) => filter,
            },
        ],
    }),

    loaders(({ values }) => ({
        elementStats: [
            null as PaginatedResponse<ElementsEventType> | null,
            {
                resetElementStats: () => emptyElementsStatsPages,
                getElementStats: async ({ url }, breakpoint) => {
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
                                          value: `^${wildcardHref.split('*').map(escapeRegex).join('.*')}$`,
                                          operator: PropertyOperator.Regex,
                                          type: PropertyFilterType.Event,
                                      },
                            ],
                            ...values.heatmapFilter,
                        }
                        const includeEventsParams = '&include=$autocapture&include=$rageclick'
                        defaultUrl = `${values.apiURL}/api/element/stats/${encodeParams(
                            { ...params, paginate_response: true },
                            '?'
                        )}${includeEventsParams}`
                    }

                    // toolbar fetch collapses queryparams but this URL has multiple with the same name
                    const response = await toolbarFetch(
                        url || defaultUrl,
                        'GET',
                        undefined,
                        url ? 'use-as-provided' : 'only-add-token'
                    )

                    if (response.status === 403) {
                        toolbarConfigLogic.actions.authenticate()
                        return emptyElementsStatsPages
                    }

                    const paginatedResults = await response.json()
                    breakpoint()

                    if (!Array.isArray(paginatedResults.results)) {
                        throw new Error('Error loading HeatMap data!')
                    }

                    return {
                        results: [...(values.elementStats?.results || []), ...paginatedResults.results],
                        next: paginatedResults.next,
                        previous: paginatedResults.previous,
                    } as PaginatedResponse<ElementsEventType>
                },
            },
        ],
    })),

    selectors(({ cache }) => ({
        dateRange: [
            (s) => [s.heatmapFilter],
            (heatmapFilter: Partial<FilterType>) => {
                return dateFilterToText(heatmapFilter.date_from, heatmapFilter.date_to, 'Last 7 days')
            },
        ],
        elements: [
            (selectors) => [
                selectors.elementStats,
                toolbarConfigLogic.selectors.dataAttributes,
                selectors.href,
                selectors.matchLinksByHref,
            ],
            (elementStats, dataAttributes, href, matchLinksByHref) => {
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
                        } catch (error) {
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
            (selectors) => [selectors.elements, toolbarConfigLogic.selectors.dataAttributes],
            (elements, dataAttributes) => {
                const normalisedElements = new Map<HTMLElement, CountedHTMLElement>()
                ;(elements || []).forEach((countedElement) => {
                    const trimmedElement = trimElement(countedElement.element)
                    if (!trimmedElement) {
                        return
                    }

                    if (normalisedElements.has(trimmedElement)) {
                        const existing = normalisedElements.get(trimmedElement)
                        if (existing) {
                            existing.count += countedElement.count
                            existing.clickCount += countedElement.type === '$rageclick' ? 0 : countedElement.count
                            existing.rageclickCount += countedElement.type === '$rageclick' ? countedElement.count : 0
                        }
                    } else {
                        normalisedElements.set(trimmedElement, {
                            ...countedElement,
                            clickCount: countedElement.type === '$rageclick' ? 0 : countedElement.count,
                            rageclickCount: countedElement.type === '$rageclick' ? countedElement.count : 0,
                            element: trimmedElement,
                            actionStep: elementToActionStep(trimmedElement, dataAttributes),
                        })
                    }
                })

                const countedElements = Array.from(normalisedElements.values())
                countedElements.sort((a, b) => b.count - a.count)

                return countedElements.map((e, i) => ({ ...e, position: i + 1 }))
            },
        ],
        elementCount: [(selectors) => [selectors.countedElements], (countedElements) => countedElements.length],
        clickCount: [
            (selectors) => [selectors.countedElements],
            (countedElements) => (countedElements ? countedElements.map((e) => e.count).reduce((a, b) => a + b, 0) : 0),
        ],
        highestClickCount: [
            (selectors) => [selectors.countedElements],
            (countedElements) =>
                countedElements ? countedElements.map((e) => e.count).reduce((a, b) => (b > a ? b : a), 0) : 0,
        ],
    })),

    afterMount(({ actions, values, cache }) => {
        if (values.heatmapEnabled) {
            actions.getElementStats()
        }
        cache.keyDownListener = (event: KeyboardEvent) => {
            if (event.shiftKey && !values.shiftPressed) {
                actions.setShiftPressed(true)
            }
        }
        cache.keyUpListener = (event: KeyboardEvent) => {
            if (!event.shiftKey && values.shiftPressed) {
                actions.setShiftPressed(false)
            }
        }
        window.addEventListener('keydown', cache.keyDownListener)
        window.addEventListener('keyup', cache.keyUpListener)
    }),

    beforeUnmount(({ cache }) => {
        window.removeEventListener('keydown', cache.keyDownListener)
        window.removeEventListener('keyup', cache.keyUpListener)
    }),

    listeners(({ actions, values }) => ({
        loadMoreElementStats: () => {
            if (values.elementStats?.next) {
                actions.getElementStats(values.elementStats.next)
            }
        },
        setHref: () => {
            if (values.heatmapEnabled) {
                actions.resetElementStats()
                actions.getElementStats()
            }
        },
        setWildcardHref: async (_, breakpoint) => {
            await breakpoint(100)
            if (values.heatmapEnabled) {
                actions.resetElementStats()
                actions.getElementStats()
            }
        },
        enableHeatmap: () => {
            actions.getElementStats()
            posthog.capture('toolbar mode triggered', { mode: 'heatmap', enabled: true })
        },
        disableHeatmap: () => {
            actions.resetElementStats()
            actions.setShowHeatmapTooltip(false)
            posthog.capture('toolbar mode triggered', { mode: 'heatmap', enabled: false })
        },
        getElementStatsSuccess: () => {
            actions.setShowHeatmapTooltip(true)
        },
        setShowHeatmapTooltip: async ({ showHeatmapTooltip }, breakpoint) => {
            if (showHeatmapTooltip) {
                await breakpoint(1000)
                actions.setShowHeatmapTooltip(false)
            }
        },
        setHeatmapFilter: () => {
            actions.resetElementStats()
            actions.getElementStats()
        },
    })),
])
