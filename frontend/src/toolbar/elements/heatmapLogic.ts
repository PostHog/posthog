// /api/projects/@current/events/?event=$autocapture&properties[pathname]=/docs/introduction/what-is-kea
import { kea } from 'kea'
import { encodeParams } from 'kea-router'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { elementToActionStep, elementToSelector, trimElement } from '~/toolbar/utils'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { heatmapLogicType } from './heatmapLogicType'
import { CountedHTMLElement, ElementsEventType } from '~/toolbar/types'
import { posthog } from '~/toolbar/posthog'
import { collectAllElementsDeep, querySelectorAllDeep } from 'query-selector-shadow-dom'

export const heatmapLogic = kea<heatmapLogicType>({
    actions: {
        enableHeatmap: true,
        disableHeatmap: true,
        setShowHeatmapTooltip: (showHeatmapTooltip: boolean) => ({ showHeatmapTooltip }),
        setHeatmapFilter: (filter: Record<string, any>) => ({ filter }),
    },

    reducers: {
        heatmapEnabled: [
            false,
            {
                enableHeatmap: () => true,
                disableHeatmap: () => false,
                getEventsFailure: () => false,
            },
        ],
        heatmapLoading: [
            false,
            {
                getEvents: () => true,
                getEventsSuccess: () => false,
                getEventsFailure: () => false,
                resetEvents: () => false,
            },
        ],
        showHeatmapTooltip: [
            false,
            {
                setShowHeatmapTooltip: (_, { showHeatmapTooltip }) => showHeatmapTooltip,
            },
        ],
        heatmapFilter: [
            {} as Record<string, any>,
            {
                setHeatmapFilter: (_, { filter }) => filter,
            },
        ],
    },

    loaders: ({ values }) => ({
        events: [
            [] as ElementsEventType[],
            {
                resetEvents: () => [],
                getEvents: async (
                    {
                        $current_url,
                    }: {
                        $current_url: string
                    },
                    breakpoint
                ) => {
                    const params: Record<string, any> = {
                        properties: [{ key: '$current_url', value: $current_url }],
                        temporary_token: toolbarLogic.values.temporaryToken,
                        ...values.heatmapFilter,
                    }

                    const url = `${toolbarLogic.values.apiURL}/api/element/stats/${encodeParams(params, '?')}`
                    const response = await fetch(url)
                    const results = await response.json()

                    if (response.status === 403) {
                        toolbarLogic.actions.authenticate()
                        return []
                    }

                    breakpoint()

                    if (!Array.isArray(results)) {
                        throw new Error('Error loading HeatMap data!')
                    }

                    return results
                },
            },
        ],
    }),

    selectors: {
        elements: [
            (selectors) => [selectors.events],
            (events) => {
                // cache all elements in shadow roots
                const allElements = collectAllElementsDeep('*', document)
                const elements: CountedHTMLElement[] = []
                events.forEach((event) => {
                    let combinedSelector
                    let lastSelector
                    for (let i = 0; i < event.elements.length; i++) {
                        const selector = elementToSelector(event.elements[i])
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
                                    console.error('Found a case with 0 elements')
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
                            throw error
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

    events: ({ actions, values }) => ({
        afterMount() {
            if (values.heatmapEnabled) {
                actions.getEvents({ $current_url: currentPageLogic.values.href })
            }
        },
    }),

    listeners: ({ actions, values }) => ({
        [currentPageLogic.actionTypes.setHref]: ({ href }) => {
            if (values.heatmapEnabled) {
                actions.resetEvents()
                actions.getEvents({ $current_url: href })
            }
        },
        enableHeatmap: () => {
            actions.getEvents({ $current_url: currentPageLogic.values.href })
            posthog.capture('toolbar mode triggered', { mode: 'heatmap', enabled: true })
        },
        disableHeatmap: () => {
            actions.resetEvents()
            actions.setShowHeatmapTooltip(false)
            posthog.capture('toolbar mode triggered', { mode: 'heatmap', enabled: false })
        },
        getEventsSuccess: () => {
            actions.setShowHeatmapTooltip(true)
        },
        setShowHeatmapTooltip: async ({ showHeatmapTooltip }, breakpoint) => {
            if (showHeatmapTooltip) {
                await breakpoint(1000)
                actions.setShowHeatmapTooltip(false)
            }
        },
        setHeatmapFilter: () => {
            actions.getEvents({ $current_url: currentPageLogic.values.href })
        },
    }),
})
