import { kea } from 'kea'
import { encodeParams } from 'kea-router'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { elementToActionStep, toolbarFetch, trimElement } from '~/toolbar/utils'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import type { heatmapLogicType } from './heatmapLogicType'
import { CountedHTMLElement, ElementsEventType } from '~/toolbar/types'
import { posthog } from '~/toolbar/posthog'
import { collectAllElementsDeep, querySelectorAllDeep } from 'query-selector-shadow-dom'
import { elementToSelector, escapeRegex } from 'lib/actionUtils'
import { FilterType, PropertyOperator } from '~/types'
import { PaginatedResponse } from 'lib/api'

export interface ElementStatsPages extends PaginatedResponse<ElementsEventType> {
    pagesLoaded: number
}

const emptyElementsStatsPages: ElementStatsPages = {
    next: undefined,
    previous: undefined,
    results: [],
    pagesLoaded: 0,
}

export const heatmapLogic = kea<heatmapLogicType>({
    path: ['toolbar', 'elements', 'heatmapLogic'],
    actions: {
        getElementStats: (url?: string | null) => ({
            url,
        }),
        enableHeatmap: true,
        disableHeatmap: true,
        setShowHeatmapTooltip: (showHeatmapTooltip: boolean) => ({ showHeatmapTooltip }),
        setShiftPressed: (shiftPressed: boolean) => ({ shiftPressed }),
        setHeatmapFilter: (filter: Partial<FilterType>) => ({ filter }),
    },

    reducers: {
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
    },

    loaders: ({ values }) => ({
        elementStats: [
            null as ElementStatsPages | null,
            {
                resetElementStats: () => emptyElementsStatsPages,
                getElementStats: async ({ url }, breakpoint) => {
                    if (url && (values.elementStats?.pagesLoaded || 0) > 10) {
                        posthog.capture('exceeded max page limit loading toolbar element stats pages', {
                            pageNumber: values.elementStats?.pagesLoaded || 0,
                            nextURL: url,
                        })
                        return { ...values.elementStats, next: undefined } as ElementStatsPages // stop paging
                    }

                    const { href, wildcardHref } = currentPageLogic.values
                    let defaultUrl: string = ''
                    if (!url) {
                        const params: Partial<FilterType> = {
                            properties: [
                                wildcardHref === href
                                    ? { key: '$current_url', value: href, operator: PropertyOperator.Exact }
                                    : {
                                          key: '$current_url',
                                          value: `^${wildcardHref.split('*').map(escapeRegex).join('.*')}$`,
                                          operator: PropertyOperator.Regex,
                                      },
                            ],
                            ...values.heatmapFilter,
                        }
                        defaultUrl = `/api/element/stats/${encodeParams({ ...params, paginate_response: true }, '?')}`
                    }

                    const response = await toolbarFetch(url || defaultUrl, 'GET', undefined, !!url)

                    if (response.status === 403) {
                        toolbarLogic.actions.authenticate()
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
                        pagesLoaded: (values.elementStats?.pagesLoaded || 0) + 1,
                    } as ElementStatsPages
                },
            },
        ],
    }),

    selectors: {
        elements: [
            (selectors) => [selectors.elementStats, toolbarLogic.selectors.dataAttributes],
            (elementStats, dataAttributes) => {
                // cache all elements in shadow roots
                const allElements = collectAllElementsDeep('*', document)
                const elements: CountedHTMLElement[] = []
                elementStats?.results.forEach((event) => {
                    let combinedSelector: string
                    let lastSelector: string | undefined
                    for (let i = 0; i < event.elements.length; i++) {
                        const selector = elementToSelector(event.elements[i], dataAttributes) || '*'
                        combinedSelector = lastSelector ? `${selector} > ${lastSelector}` : selector

                        try {
                            const domElements = Array.from(
                                querySelectorAllDeep(combinedSelector, document, allElements)
                            ) as HTMLElement[]

                            if (domElements.length === 1) {
                                const e = event.elements[i]

                                // element like "svg" (only tag, no class/id/etc) as the first one
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
                                    } as CountedHTMLElement)
                                    return null
                                }
                            }

                            if (domElements.length === 0) {
                                if (i === event.elements.length - 1) {
                                    console.error(
                                        'For event: ',
                                        event,
                                        '. Found a case with 0 elements using: ',
                                        combinedSelector
                                    )
                                    return null
                                } else if (i > 0 && lastSelector) {
                                    // We already have something, but found nothing when adding the next selector.
                                    // Skip it and try with the next one...
                                    lastSelector = lastSelector ? `* > ${lastSelector}` : '*'
                                    continue
                                } else {
                                    console.log('Found empty selector')
                                }
                            }
                        } catch (error) {
                            console.error('Invalid selector!', combinedSelector)
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
            (selectors) => [selectors.elements, toolbarLogic.selectors.dataAttributes],
            (elements, dataAttributes) => {
                const elementCounter = new Map<HTMLElement, number>()
                const elementSelector = new Map<HTMLElement, string>()

                ;(elements || []).forEach(({ element, selector, count }) => {
                    const trimmedElement = trimElement(element)
                    if (trimmedElement) {
                        const oldCount = elementCounter.get(trimmedElement) || 0
                        elementCounter.set(trimmedElement, oldCount + count)
                        if (oldCount === 0) {
                            elementSelector.set(trimmedElement, selector)
                        }
                    }
                })

                const countedElements = [] as CountedHTMLElement[]
                elementCounter.forEach((count, element) => {
                    const selector = elementSelector.get(element)
                    countedElements.push({
                        count,
                        element,
                        selector,
                        actionStep: elementToActionStep(element, dataAttributes),
                    } as CountedHTMLElement)
                })

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
    },

    events: ({ actions, values, cache }) => ({
        afterMount() {
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
        },
        beforeUnmount() {
            window.removeEventListener('keydown', cache.keyDownListener)
            window.removeEventListener('keyup', cache.keyUpListener)
        },
    }),

    listeners: ({ actions, values }) => ({
        [currentPageLogic.actionTypes.setHref]: () => {
            if (values.heatmapEnabled) {
                actions.resetElementStats()
                actions.getElementStats()
            }
        },
        [currentPageLogic.actionTypes.setWildcardHref]: async (_, breakpoint) => {
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
        getElementStatsSuccess: ({ elementStats }) => {
            if (elementStats?.next) {
                actions.getElementStats(elementStats.next)
            } else {
                posthog.capture('loaded every toolbar element stats pages', {
                    pageNumber: elementStats?.pagesLoaded,
                    finalPage: elementStats?.previous,
                })
            }
            actions.setShowHeatmapTooltip(true)
        },
        setShowHeatmapTooltip: async ({ showHeatmapTooltip }, breakpoint) => {
            if (showHeatmapTooltip) {
                await breakpoint(1000)
                actions.setShowHeatmapTooltip(false)
            }
        },
        setHeatmapFilter: () => {
            actions.getElementStats()
        },
    }),
})
