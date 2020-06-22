import { kea } from 'kea'

import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { elementToActionStep, getAllClickTargets, getElementForStep } from '~/toolbar/elements/utils'
import { dockLogic } from '~/toolbar/dockLogic'
import { toolbarTabLogic } from '~/toolbar/toolbarTabLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'

export const elementsLogic = kea({
    actions: {
        enableInspect: true,
        disableInspect: true,

        updateRects: true,
        setHoverElement: element => ({ element }),
        setHighlightElement: element => ({ element }),
        setSelectedElement: element => ({ element }),
    },

    reducers: () => ({
        inspectEnabledRaw: [
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
            setHoverElement: () => null,
            setSelectedElement: () => null,
            disableInspect: () => null,
        },
        selectedElement: {
            setSelectedElement: (_, { element }) => element,
            disableInspect: () => null,
            [heatmapLogic.actions.disableHeatmap]: () => null,
        },
        enabledLast: {
            // keep track of what to disable first with ESC
            enableInspect: () => 'inspect',
            [heatmapLogic.actions.enableHeatmap]: () => 'heatmap',
        },
    }),

    selectors: {
        inspectEnabled: [
            selectors => [
                selectors.inspectEnabledRaw,
                toolbarTabLogic.selectors.tab,
                actionsTabLogic.selectors.inspectingElement,
            ],
            (inpsectEnabledRaw, tab, inspectingElement) =>
                tab === 'stats' ? inpsectEnabledRaw : tab === 'actions' ? inspectingElement !== null : false,
        ],

        heatmapEnabled: [
            () => [heatmapLogic.selectors.heatmapEnabled, toolbarTabLogic.selectors.tab],
            (heatmapEnabled, tab) => heatmapEnabled && tab === 'stats',
        ],

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

        actionsForElementMap: [
            selectors => [actionsLogic.selectors.actionsForCurrentUrl, selectors.rectUpdateCounter],
            actionsForCurrentUrl => {
                const actionsForElementMap = new Map()
                actionsForCurrentUrl.forEach(action => {
                    action.steps
                        .filter(step => step.event === '$autocapture')
                        .forEach(step => {
                            const element = getElementForStep(step)
                            if (element) {
                                const rect = element.getBoundingClientRect()
                                let array = actionsForElementMap.get(element)
                                if (!array) {
                                    array = []
                                    actionsForElementMap.set(element, array)
                                }
                                array.push({ action, step, element, rect })
                            }
                        })
                })
                return actionsForElementMap
            },
        ],

        elementsWithActions: [
            selectors => [selectors.actionsForElementMap],
            actionsForElementMap => [...actionsForElementMap.keys()],
        ],

        actionLabelsToDisplay: [
            selectors => [selectors.elementsWithActions, selectors.inspectEnabled],
            (elementsWithActions, inspectEnabled) => (inspectEnabled ? elementsWithActions : []),
        ],

        selectedElementMeta: [
            selectors => [selectors.selectedElement, selectors.elementMap, selectors.actionsForElementMap],
            (selectedElement, elementMap, actionsForElementMap) => {
                const meta = elementMap.get(selectedElement)
                const actions = actionsForElementMap.get(selectedElement)
                return meta
                    ? {
                          ...meta,
                          actionStep: meta.actionStep || elementToActionStep(meta.element),
                          actions: actions || [],
                      }
                    : null
            },
        ],

        hoverElementMeta: [
            selectors => [selectors.hoverElement, selectors.elementMap, selectors.actionsForElementMap],
            (hoverElement, elementMap, actionsForElementMap) => {
                const meta = elementMap.get(hoverElement)
                const actions = actionsForElementMap.get(hoverElement)
                return meta
                    ? {
                          ...meta,
                          actionStep: meta.actionStep || elementToActionStep(meta.element),
                          actions: actions || [],
                      }
                    : null
            },
        ],

        highlightElementMeta: [
            selectors => [selectors.highlightElement, selectors.elementMap, selectors.actionsForElementMap],
            (highlightElement, elementMap, actionsForElementMap) => {
                const meta = elementMap.get(highlightElement)
                const actions = actionsForElementMap.get(highlightElement)
                return meta
                    ? {
                          ...meta,
                          actionStep: meta.actionStep || elementToActionStep(meta.element),
                          actions: actions || [],
                      }
                    : null
            },
        ],
    },

    events: ({ cache, values, actions }) => ({
        afterMount: () => {
            cache.onClick = () => actions.updateRects()
            cache.onScrollResize = () => {
                window.clearTimeout(cache.clickDelayTimeout)
                actions.updateRects()
                cache.clickDelayTimeout = window.setTimeout(actions.addClick, 100)
            }
            cache.onKeyDown = e => {
                if (e.keyCode !== 27) {
                    return
                }
                if (values.hoverElement) {
                    actions.setHoverElement(null)
                }
                if (values.selectedElement) {
                    actions.setSelectedElement(null)
                    return
                }
                if (values.enabledLast === 'heatmap' && values.heatmapEnabled) {
                    heatmapLogic.actions.disableHeatmap()
                    return
                }
                if (values.inspectEnabled) {
                    actions.disableInspect()
                    return
                }
                if (values.heatmapEnabled) {
                    heatmapLogic.actions.disableHeatmap()
                    return
                }
            }
            window.addEventListener('click', cache.onClick)
            window.addEventListener('scroll', cache.onScrollResize)
            window.addEventListener('resize', cache.onScrollResize)
            window.addEventListener('keydown', cache.onKeyDown)
        },
        beforeUnmount: () => {
            window.removeEventListener('click', cache.onClick)
            window.removeEventListener('scroll', cache.onScrollResize)
            window.removeEventListener('resize', cache.onScrollResize)
            window.removeEventListener('keydown', cache.onKeyDown)
        },
    }),

    listeners: () => ({
        enableInspect: () => {
            actionsLogic.actions.getActions()
        },
    }),
})
