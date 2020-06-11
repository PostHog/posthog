// /api/event/?event=$autocapture&properties[pathname]=/docs/introduction/what-is-kea

import { kea } from 'kea'
import { encodeParams } from 'kea-router'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { dockLogic } from '~/toolbar/dockLogic'
import { elementToActionStep, elementToSelector } from '~/toolbar/shared/utils'

export const heatmapLogic = kea({
    actions: () => ({
        addClick: true,
        highlightElement: (element, withElementFinder = false) => ({ element, withElementFinder }),
        setHeatmapEnabled: heatmapEnabled => ({ heatmapEnabled }),
    }),

    reducers: () => ({
        heatmapEnabled: [
            false,
            {
                setHeatmapEnabled: (_, { heatmapEnabled }) => heatmapEnabled,
            },
        ],
        clicks: [
            0,
            {
                addClick: state => state + 1,
            },
        ],
        highlightedElement: [
            null,
            {
                highlightElement: (_, { element }) => element,
                setHeatmapEnabled: (state, { heatmapEnabled }) => (heatmapEnabled ? state : null),
            },
        ],
        showElementFinder: [
            false,
            {
                highlightElement: (_, { withElementFinder }) => withElementFinder,
                setHeatmapEnabled: (state, { heatmapEnabled }) => (heatmapEnabled ? state : null),
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
    }),

    loaders: ({ props }) => ({
        events: [
            [],
            {
                resetEvents: () => [],
                getEvents: ({ $current_url }, breakpoint) => {
                    const results = fetch(
                        `${props.apiURL}api/event/?${encodeParams(
                            {
                                event: '$autocapture',
                                properties: { $current_url },
                                temporary_token: props.temporaryToken,
                            },
                            ''
                        )}`
                    )
                        .then(response => response.json())
                        .then(response => response.results)

                    breakpoint()

                    return results
                },
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        elements: [
            () => [selectors.events],
            events => {
                console.log({ events })

                const elements = events
                    .map(event => {
                        console.log(event.properties['$event_type'])
                        let combinedSelector
                        for (let i = 0; i < event.elements.length; i++) {
                            const selector = elementToSelector(event.elements[i])
                            combinedSelector = combinedSelector ? `${selector} > ${combinedSelector}` : selector

                            const elements = Array.from(document.querySelectorAll(combinedSelector)).filter(
                                e => e.getBoundingClientRect().width > 0
                            )

                            if (elements.length === 1) {
                                return {
                                    element: elements[0],
                                    selector,
                                    event,
                                }
                            }

                            if (elements.length === 0 && i === 0) {
                                console.error('found a case with 0 elements')
                                return null
                            }

                            // not the last one in the loop
                            if (i !== event.elements.length - 1) {
                                continue
                            }

                            // debugger

                            // return {
                            //     selector,
                            //     event,
                            // }
                        }
                    })
                    .filter(e => e)

                console.log({ elements })
                return elements
            },
        ],
        countedElements: [
            () => [selectors.elements],
            elements => {
                const elementCounter = new Map()
                const elementSelector = new Map()
                elements.forEach(({ element, selector }) => {
                    const count = elementCounter.get(element) || 0
                    elementCounter.set(element, count + 1)
                    if (count === 0) {
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

                return countedElements
            },
        ],
        countedElementsWithRects: [
            () => [
                selectors.countedElements,
                selectors.clicks,
                selectors.highlightedElement,
                dockLogic.selectors.dockStatus,
                dockLogic.selectors.zoom,
            ],
            countedElements => countedElements.map(e => ({ ...e, rect: e.element.getBoundingClientRect() })),
        ],
        eventCount: [
            () => [selectors.countedElements],
            countedElements => (countedElements ? countedElements.map(e => e.count).reduce((a, b) => a + b, 0) : 0),
        ],
        highestEventCount: [
            () => [selectors.countedElements],
            countedElements =>
                countedElements ? countedElements.map(e => e.count).reduce((a, b) => (b > a ? b : a), 0) : 0,
        ],
        highlightedElementMeta: [
            () => [selectors.highlightedElement, selectors.countedElementsWithRects],
            (highlightedElement, countedElementsWithRects) => {
                const meta = highlightedElement
                    ? countedElementsWithRects.find(({ element }) => element === highlightedElement)
                    : null

                if (meta) {
                    return { ...meta, actionStep: elementToActionStep(meta.element) }
                }

                return null
            },
        ],
    }),

    events: ({ actions, values, cache }) => ({
        afterMount() {
            if (values.heatmapEnabled) {
                actions.getEvents({ $current_url: currentPageLogic.values.href })
            }
            cache.onClick = function() {
                actions.addClick()
            }
            window.addEventListener('click', cache.onClick)
        },
        beforeUnmount() {
            window.removeEventListener('click', cache.onClick)
        },
    }),

    listeners: ({ actions, values }) => ({
        [currentPageLogic.actions.setHref]: ({ href }) => {
            if (values.heatmapEnabled) {
                actions.resetEvents()
                actions.getEvents({ $current_url: href })
            }
        },
        setHeatmapEnabled: ({ heatmapEnabled }) => {
            if (heatmapEnabled) {
                actions.getEvents({ $current_url: currentPageLogic.values.href })
            } else {
                actions.resetEvents()
            }
        },
    }),
})
