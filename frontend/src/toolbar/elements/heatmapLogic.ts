// /api/event/?event=$autocapture&properties[pathname]=/docs/introduction/what-is-kea

import { kea } from 'kea'
import { encodeParams } from 'kea-router'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { elementToActionStep, elementToSelector } from '~/toolbar/utils'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { heatmapLogicType } from 'types/toolbar/elements/heatmapLogicType'
import { CountedHTMLElement, ElementsEventType } from '~/toolbar/types'
import { ActionStepType } from '~/types'

export const heatmapLogic = kea<heatmapLogicType<ElementsEventType, CountedHTMLElement, ActionStepType>>({
    actions: {
        enableHeatmap: true,
        disableHeatmap: true,
        setShowHeatmapTooltip: (showHeatmapTooltip: boolean) => ({ showHeatmapTooltip }),
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
    },

    loaders: {
        events: [
            [] as ElementsEventType[],
            {
                resetEvents: () => [],
                getEvents: async ({ $current_url }: { $current_url: string }, breakpoint) => {
                    const params = {
                        properties: [{ key: '$current_url', value: $current_url }],
                        temporary_token: toolbarLogic.values.temporaryToken,
                    }
                    const url = `${toolbarLogic.values.apiURL}api/element/stats/${encodeParams(params, '?')}`
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
    },

    selectors: {
        elements: [
            (selectors) => [selectors.events],
            (events) => {
                const elements: CountedHTMLElement[] = []
                events.forEach((event) => {
                    let combinedSelector
                    for (let i = 0; i < event.elements.length; i++) {
                        const selector = elementToSelector(event.elements[i])
                        combinedSelector = combinedSelector ? `${selector} > ${combinedSelector}` : selector

                        try {
                            const domElements = Array.from(document.querySelectorAll(combinedSelector))

                            if (domElements.length === 1) {
                                elements.push({
                                    element: domElements[0],
                                    count: event.count,
                                    selector: selector,
                                    hash: event.hash,
                                } as CountedHTMLElement)
                                return null
                            }

                            if (domElements.length === 0 && i === event.elements.length - 1) {
                                console.error('Found a case with 0 elements')
                                return null
                            }
                        } catch (error) {
                            console.error('Invalid selector!', combinedSelector)
                            throw error
                        }

                        // TODO: what if multiple elements will continue to match until the end?
                    }
                })

                return elements
            },
        ],
        countedElements: [
            (selectors) => [selectors.elements],
            (elements) => {
                const elementCounter = new Map<HTMLElement, number>()
                const elementSelector = new Map<HTMLElement, string>()

                ;(elements || []).forEach(({ element, selector, count }) => {
                    const oldCount = elementCounter.get(element) || 0
                    elementCounter.set(element, oldCount + count)
                    if (oldCount === 0) {
                        elementSelector.set(element, selector)
                    }
                })

                const countedElements = [] as CountedHTMLElement[]
                elementCounter.forEach((count, element) => {
                    const selector = elementSelector.get(element)
                    countedElements.push({
                        count,
                        element,
                        selector,
                        actionStep: elementToActionStep(element),
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
        },
        disableHeatmap: () => {
            actions.resetEvents()
            actions.setShowHeatmapTooltip(false)
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
    }),
})
