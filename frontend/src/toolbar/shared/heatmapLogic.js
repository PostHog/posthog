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
    }),

    reducers: () => ({
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
            },
        ],
        showElementFinder: [
            false,
            {
                highlightElement: (_, { withElementFinder }) => withElementFinder,
            },
        ],
    }),

    loaders: ({ props }) => ({
        events: [
            [],
            {
                resetEvents: () => [],
                getEvents: ({ $current_url }) =>
                    fetch(
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
                        .then(response => response.results),
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
                dockLogic.selectors.dockStatus,
                dockLogic.selectors.zoom,
            ],
            countedElements => countedElements.map(e => ({ ...e, rect: e.element.getBoundingClientRect() })),
        ],
        eventCount: [
            () => [selectors.countedElements],
            countedElements => countedElements.map(e => e.count).reduce((a, b) => a + b, 0),
        ],
    }),

    events: ({ actions, props, cache }) => ({
        afterMount() {
            actions.getEvents({ $current_url: props.current_url })
            cache.onClick = function() {
                actions.addClick()
            }
            window.addEventListener('click', cache.onClick)
        },
        beforeUnmount() {
            window.removeEventListener('click', cache.onClick)
        },
    }),

    listeners: ({ actions }) => ({
        [currentPageLogic.actions.setHref]: ({ href }) => {
            actions.resetEvents()
            actions.getEvents({ $current_url: href })
        },
    }),
})
