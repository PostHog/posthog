// /api/event/?event=$autocapture&properties[pathname]=/docs/introduction/what-is-kea

import { kea } from 'kea'
import { encodeParams } from 'kea-router'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { elementToActionStep, elementToSelector } from '~/toolbar/elements/utils'
import { toolbarLogic } from '~/toolbar/toolbarLogic'

export const heatmapLogic = kea({
    actions: {
        enableHeatmap: true,
        disableHeatmap: true,
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
    },

    loaders: {
        events: [
            [],
            {
                resetEvents: () => [],
                getEvents: async ({ $current_url }, breakpoint) => {
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
            selectors => [selectors.events],
            events => {
                const elements = events
                    .map(event => {
                        let combinedSelector
                        for (let i = 0; i < event.elements.length; i++) {
                            const selector = elementToSelector(event.elements[i])
                            combinedSelector = combinedSelector ? `${selector} > ${combinedSelector}` : selector

                            try {
                                const elements = Array.from(document.querySelectorAll(combinedSelector))

                                if (elements.length === 1) {
                                    return {
                                        element: elements[0],
                                        count: event.count,
                                        selector: selector,
                                        hash: event.hash,
                                    }
                                }

                                if (elements.length === 0 && i === event.elements.length - 1) {
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
                    .filter(e => e)

                return elements
            },
        ],
        countedElements: [
            selectors => [selectors.elements],
            elements => {
                const elementCounter = new Map()
                const elementSelector = new Map()
                elements.forEach(({ element, selector, count }) => {
                    const oldCount = elementCounter.get(element) || 0
                    elementCounter.set(element, oldCount + count)
                    if (oldCount === 0) {
                        elementSelector.set(element, selector)
                    }
                })

                const countedElements = []
                elementCounter.forEach((count, element) => {
                    const selector = elementSelector[element]
                    countedElements.push({
                        count,
                        element,
                        selector,
                        actionStep: elementToActionStep(element),
                    })
                })

                countedElements.sort((a, b) => b.count - a.count)

                return countedElements.map((e, i) => ({ ...e, position: i + 1 }))
            },
        ],
        elementCount: [selectors => [selectors.countedElements], countedElements => countedElements.length],
        clickCount: [
            selectors => [selectors.countedElements],
            countedElements => (countedElements ? countedElements.map(e => e.count).reduce((a, b) => a + b, 0) : 0),
        ],
        highestClickCount: [
            selectors => [selectors.countedElements],
            countedElements =>
                countedElements ? countedElements.map(e => e.count).reduce((a, b) => (b > a ? b : a), 0) : 0,
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
        [currentPageLogic.actions.setHref]: ({ href }) => {
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
        },
    }),
})
