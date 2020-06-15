import { kea } from 'kea'

import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { elementToActionStep, getAllClickTargets } from '~/toolbar/elements/utils'
import { dockLogic } from '~/toolbar/dockLogic'

export const elementsLogic = kea({
    actions: {
        enableInspect: true,
        disableInspect: true,

        updateRects: true,
        setHoverElement: (element, highlight = false) => ({ element, highlight }),
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
        hoverElementHighlight: {
            setHoverElement: (_, { highlight }) => highlight,
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
                if (!meta) {
                    return null
                }
                return {
                    ...meta,
                    actionStep: meta.actionStep || elementToActionStep(meta.element),
                }
            },
        ],

        hoverElementMeta: [
            selectors => [selectors.hoverElement, selectors.elementMap],
            (hoverElement, elementMap) => {
                const meta = elementMap.get(hoverElement)
                if (!meta) {
                    return null
                }
                return {
                    ...meta,
                    actionStep: meta.actionStep || elementToActionStep(meta.element),
                }
            },
        ],
    },

    events: ({ cache, actions }) => ({
        afterMount: () => {
            cache.onClick = () => actions.updateRects()
            cache.onScroll = function() {
                window.clearTimeout(cache.clickDelayTimeout)
                actions.updateRects()
                cache.clickDelayTimeout = window.setTimeout(actions.addClick, 100)
            }
            window.addEventListener('click', cache.onClick)
            window.addEventListener('scroll', cache.onScroll)
        },
        beforeUnmount: () => {
            window.removeEventListener('click', cache.onClick)
            window.removeEventListener('scroll', cache.onScroll)
        },
    }),
})
