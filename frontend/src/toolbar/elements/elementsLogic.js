import { kea } from 'kea'

import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { elementToActionStep, getAllClickTargets, getElementForStep } from '~/toolbar/utils'
import { dockLogic } from '~/toolbar/dockLogic'
import { toolbarTabLogic } from '~/toolbar/toolbarTabLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'

export const elementsLogic = kea({
    actions: {
        enableInspect: true,
        disableInspect: true,

        selectElement: (element) => ({ element }),
        createAction: (element) => ({ element }),

        updateRects: true,
        setHoverElement: (element) => ({ element }),
        setHighlightElement: (element) => ({ element }),
        setSelectedElement: (element) => ({ element }),
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
                updateRects: (state) => state + 1,
            },
        ],
        hoverElement: {
            setHoverElement: (_, { element }) => element,
            enableInspect: () => null,
            disableInspect: () => null,
            createAction: () => null,
            [toolbarTabLogic.actions.setTab]: () => null,
        },
        highlightElement: {
            setHighlightElement: (_, { element }) => element,
            setHoverElement: () => null,
            setSelectedElement: () => null,
            selectElement: () => null,
            disableInspect: () => null,
            createAction: () => null,
            [toolbarTabLogic.actions.setTab]: () => null,
        },
        selectedElement: {
            setSelectedElement: (_, { element }) => element,
            disableInspect: () => null,
            createAction: () => null,
            [toolbarTabLogic.actions.setTab]: () => null,
            [heatmapLogic.actions.disableHeatmap]: () => null,
            [actionsTabLogic.actions.selectAction]: () => null,
        },
        enabledLast: {
            // keep track of what to disable first with ESC
            enableInspect: () => 'inspect',
            [heatmapLogic.actions.enableHeatmap]: () => 'heatmap',
        },
    }),

    selectors: {
        inspectEnabled: [
            (s) => [
                dockLogic.selectors.mode,
                s.inspectEnabledRaw,
                toolbarTabLogic.selectors.tab,
                actionsTabLogic.selectors.inspectingElement,
                actionsTabLogic.selectors.buttonActionsVisible,
            ],
            (mode, inpsectEnabledRaw, tab, inspectingElement, buttonActionsVisible) =>
                mode === 'dock'
                    ? tab === 'stats'
                        ? inpsectEnabledRaw
                        : tab === 'actions'
                        ? inspectingElement !== null
                        : false
                    : inpsectEnabledRaw || (buttonActionsVisible && inspectingElement !== null),
        ],

        heatmapEnabled: [
            () => [heatmapLogic.selectors.heatmapEnabled, toolbarTabLogic.selectors.tab],
            (heatmapEnabled, tab) => heatmapEnabled && tab === 'stats',
        ],

        heatmapElements: [
            (s) => [heatmapLogic.selectors.countedElements, s.rectUpdateCounter, dockLogic.selectors.isAnimating],
            (countedElements) => countedElements.map((e) => ({ ...e, rect: e.element.getBoundingClientRect() })),
        ],

        allInspectElements: [
            (s) => [s.inspectEnabled],
            (inspectEnabled) => (inspectEnabled ? getAllClickTargets() : []),
        ],

        inspectElements: [
            (s) => [s.allInspectElements, s.rectUpdateCounter, dockLogic.selectors.isAnimating],
            (allInspectElements) =>
                allInspectElements.map((element) => ({ element, rect: element.getBoundingClientRect() })),
        ],

        displayActionElements: [
            () => [
                dockLogic.selectors.mode,
                toolbarTabLogic.selectors.tab,
                actionsTabLogic.selectors.buttonActionsVisible,
            ],
            (mode, tab, buttonActionsVisible) => (mode === 'button' ? buttonActionsVisible : tab === 'actions'),
        ],

        allActionElements: [
            (s) => [s.displayActionElements, actionsTabLogic.selectors.selectedEditedAction],
            (displayActionElements, selectedEditedAction) => {
                if (displayActionElements && selectedEditedAction?.steps) {
                    return selectedEditedAction.steps
                        .map((step, index) => ({
                            element: getElementForStep(step),
                            index,
                        }))
                        .filter((e) => e.element)
                }
                return []
            },
        ],

        actionElements: [
            (s) => [s.allActionElements, s.rectUpdateCounter, dockLogic.selectors.isAnimating],
            (allActionElements) =>
                allActionElements.map((element) =>
                    element.element ? { ...element, rect: element.element.getBoundingClientRect() } : element
                ),
        ],

        elementMap: [
            (s) => [s.heatmapElements, s.inspectElements, s.actionElements, s.actionsListElements],
            (heatmapElements, inspectElements, actionElements, actionsListElements) => {
                const elementMap = new Map()

                inspectElements.forEach((e) => {
                    elementMap.set(e.element, e)
                })
                heatmapElements.forEach((e) => {
                    if (elementMap.get(e.element)) {
                        elementMap.set(e.element, { ...elementMap.get(e.element), ...e })
                    } else {
                        elementMap.set(e.element, e)
                    }
                })
                ;[...actionElements, ...actionsListElements].forEach((e) => {
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
            (s) => [actionsLogic.selectors.actionsForCurrentUrl, s.rectUpdateCounter, dockLogic.selectors.isAnimating],
            (actionsForCurrentUrl) => {
                const actionsForElementMap = new Map()
                actionsForCurrentUrl.forEach((action, index) => {
                    action.steps
                        .filter((step) => step.event === '$autocapture')
                        .forEach((step) => {
                            const element = getElementForStep(step)
                            if (element) {
                                const rect = element.getBoundingClientRect()
                                let array = actionsForElementMap.get(element)
                                if (!array) {
                                    array = []
                                    actionsForElementMap.set(element, array)
                                }
                                array.push({ action, step, element, rect, index })
                            }
                        })
                })
                return actionsForElementMap
            },
        ],

        elementsWithActions: [
            (s) => [s.actionsForElementMap],
            (actionsForElementMap) => [...actionsForElementMap.keys()],
        ],

        actionsListElements: [
            (s) => [s.actionsForElementMap],
            (actionsForElementMap) => [...actionsForElementMap.values()].map((a) => a[0]),
        ],

        elementsToDisplayRaw: [
            (s) => [
                s.displayActionElements,
                s.actionElements,
                s.inspectElements,
                s.actionsListElements,
                actionsTabLogic.selectors.selectedAction,
            ],
            (displayActionElements, actionElements, inspectElements, actionsListElements, selectedAction) => {
                if (inspectElements.length > 0) {
                    return inspectElements
                }
                if (displayActionElements && selectedAction && actionElements.length > 0) {
                    return actionElements
                }
                if (displayActionElements && !selectedAction && actionsListElements.length > 0) {
                    return actionsListElements
                }
                return []
            },
        ],

        elementsToDisplay: [
            (s) => [s.elementsToDisplayRaw],
            (elementsToDisplayRaw) => {
                return elementsToDisplayRaw.filter(({ rect }) => rect.width !== 0 || rect.height !== 0)
            },
        ],

        labelsToDisplay: [
            (s) => [
                s.displayActionElements,
                s.actionElements,
                s.actionsListElements,
                actionsTabLogic.selectors.selectedAction,
            ],
            (displayActionElements, actionElements, actionsListElements, selectedAction) => {
                if (displayActionElements && selectedAction && actionElements.length > 0) {
                    return actionElements
                }
                if (displayActionElements && !selectedAction && actionsListElements.length > 0) {
                    return actionsListElements
                }
                return []
            },
        ],

        actionLabelsToDisplay: [
            (s) => [s.elementsWithActions, s.inspectEnabled, s.displayActionElements],
            (elementsWithActions, inspectEnabled, displayActionElements) =>
                inspectEnabled && !displayActionElements ? elementsWithActions : [],
        ],

        selectedElementMeta: [
            (s) => [s.selectedElement, s.elementMap, s.actionsForElementMap],
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
            (s) => [s.hoverElement, s.elementMap, s.actionsForElementMap],
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
            (s) => [s.highlightElement, s.elementMap, s.actionsForElementMap],
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
            cache.onKeyDown = (e) => {
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
            window.addEventListener('resize', cache.onScrollResize)
            window.addEventListener('keydown', cache.onKeyDown)
            window.document.addEventListener('scroll', cache.onScrollResize, true)
        },
        beforeUnmount: () => {
            window.removeEventListener('click', cache.onClick)
            window.removeEventListener('resize', cache.onScrollResize)
            window.removeEventListener('keydown', cache.onKeyDown)
            window.document.removeEventListener('scroll', cache.onScrollResize, true)
        },
    }),

    listeners: ({ actions }) => ({
        enableInspect: () => {
            actionsLogic.actions.getActions()
        },
        selectElement: ({ element }) => {
            const inpsectForAction =
                (dockLogic.values.mode === 'dock'
                    ? toolbarTabLogic.values.tab === 'actions'
                    : actionsTabLogic.values.buttonActionsVisible) && actionsTabLogic.values.inspectingElement !== null

            if (inpsectForAction) {
                actions.setHoverElement(null)
                actionsTabLogic.actions.inspectElementSelected(element, actionsTabLogic.values.inspectingElement)
            } else {
                actions.setSelectedElement(element)
            }
        },
        createAction: ({ element }) => {
            if (dockLogic.values.mode === 'button') {
                actionsTabLogic.actions.showButtonActions()
                toolbarButtonLogic.actions.showActionsInfo()
                elementsLogic.actions.selectElement(null)
            } else {
                toolbarTabLogic.actions.setTab('actions')
            }
            actionsTabLogic.actions.newAction(element)
        },
    }),
})
