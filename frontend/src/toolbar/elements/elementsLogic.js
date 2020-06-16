import { kea } from 'kea'

import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { elementToActionStep, getAllClickTargets } from '~/toolbar/elements/utils'
import { dockLogic } from '~/toolbar/dockLogic'

export const elementsLogic = kea({
    actions: {
        enableInspect: true,
        disableInspect: true,

        updateRects: true,
        setHoverElement: element => ({ element }),
        setHighlightElement: element => ({ element }),
        setSelectedElement: element => ({ element }),
    },

    reducers: {
        inspectEnabled: [
            false,
            {
                enableInspect: () => true,
                disableInspect: () => false,
            },
        ],
        rectUpdateCounter: [
            0,
            {
                updateRects: state => state + 1,
            },
        ],
        hoverElement: {
            setHoverElement: (_, { element }) => element,
        },
        highlightElement: {
            setHighlightElement: (_, { element }) => element,
        },
        selectedElement: {
            setSelectedElement: (_, { element }) => element,
        },
    },

    selectors: {
        heatmapEnabled: [() => [heatmapLogic.selectors.heatmapEnabled], heatmapEnabled => heatmapEnabled],

        heatmapElements: [
            selectors => [
                heatmapLogic.selectors.countedElements,
                selectors.rectUpdateCounter,
                dockLogic.selectors.isAnimating,
            ],
            countedElements => countedElements.map(e => ({ ...e, rect: e.element.getBoundingClientRect() })),
        ],

        allInspectElements: [
            selectors => [selectors.inspectEnabled],
            inspectEnabled => (inspectEnabled ? getAllClickTargets() : []),
        ],

        inspectElements: [
            selectors => [selectors.allInspectElements, selectors.rectUpdateCounter, dockLogic.selectors.isAnimating],
            selectableElements =>
                selectableElements.map(element => ({ element, rect: element.getBoundingClientRect() })),
        ],

        elementMap: [
            selectors => [selectors.heatmapElements, selectors.inspectElements],
            (heatmapElements, inspectElements) => {
                const elementMap = new Map()
                inspectElements.forEach(e => {
                    elementMap.set(e.element, e)
                })
                heatmapElements.forEach(e => {
                    if (elementMap.get(e.element)) {
                        elementMap.set(e.element, { ...elementMap.get(e.element), ...e })
                    } else {
                        elementMap.set(e.element, e)
                    }
                })
                return elementMap
            },
        ],

        selectedElementMeta: [
            selectors => [selectors.selectedElement, selectors.elementMap],
            (selectedElement, elementMap) => {
                const meta = elementMap.get(selectedElement)
                return meta
                    ? {
                          ...meta,
                          actionStep: meta.actionStep || elementToActionStep(meta.element),
                      }
                    : null
            },
        ],

        hoverElementMeta: [
            selectors => [selectors.hoverElement, selectors.elementMap],
            (hoverElement, elementMap) => {
                const meta = elementMap.get(hoverElement)
                return meta
                    ? {
                          ...meta,
                          actionStep: meta.actionStep || elementToActionStep(meta.element),
                      }
                    : null
            },
        ],

        highlightElementMeta: [
            selectors => [selectors.highlightElement, selectors.elementMap],
            (highlightElement, elementMap) => {
                const meta = elementMap.get(highlightElement)
                return meta
                    ? {
                          ...meta,
                          actionStep: meta.actionStep || elementToActionStep(meta.element),
                      }
                    : null
            },
        ],
    },

    events: ({ cache, actions }) => ({
        afterMount: () => {
            cache.onClick = () => actions.updateRects()
            cache.onScrollResize = function() {
                window.clearTimeout(cache.clickDelayTimeout)
                actions.updateRects()
                cache.clickDelayTimeout = window.setTimeout(actions.addClick, 100)
            }
            window.addEventListener('click', cache.onClick)
            window.addEventListener('scroll', cache.onScrollResize)
            window.addEventListener('resize', cache.onScrollResize)
        },
        beforeUnmount: () => {
            window.removeEventListener('click', cache.onClick)
            window.removeEventListener('scroll', cache.onScrollResize)
            window.removeEventListener('resize', cache.onScrollResize)
        },
    }),
})
