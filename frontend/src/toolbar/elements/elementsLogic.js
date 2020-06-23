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

        selectElement: element => ({ element }),
        createAction: element => ({ element }),

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
            enableInspect: () => null,
            disableInspect: () => null,
            createAction: () => null,
        },
        highlightElement: {
            setHighlightElement: (_, { element }) => element,
            setHoverElement: () => null,
            setSelectedElement: () => null,
            selectElement: () => null,
            disableInspect: () => null,
            createAction: () => null,
        },
        selectedElement: {
            setSelectedElement: (_, { element }) => element,
            disableInspect: () => null,
            createAction: () => null,
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
            s => [s.inspectEnabledRaw, toolbarTabLogic.selectors.tab, actionsTabLogic.selectors.inspectingElement],
            (inpsectEnabledRaw, tab, inspectingElement) =>
                tab === 'stats' ? inpsectEnabledRaw : tab === 'actions' ? inspectingElement !== null : false,
        ],

        heatmapEnabled: [
            () => [heatmapLogic.selectors.heatmapEnabled, toolbarTabLogic.selectors.tab],
            (heatmapEnabled, tab) => heatmapEnabled && tab === 'stats',
        ],

        heatmapElements: [
            s => [heatmapLogic.selectors.countedElements, s.rectUpdateCounter, dockLogic.selectors.isAnimating],
            countedElements => countedElements.map(e => ({ ...e, rect: e.element.getBoundingClientRect() })),
        ],

        allInspectElements: [s => [s.inspectEnabled], inspectEnabled => (inspectEnabled ? getAllClickTargets() : [])],

        inspectElements: [
            s => [s.allInspectElements, s.rectUpdateCounter, dockLogic.selectors.isAnimating],
            allInspectElements =>
                allInspectElements.map(element => ({ element, rect: element.getBoundingClientRect() })),
        ],

        allActionElements: [
            () => [toolbarTabLogic.selectors.tab, actionsTabLogic.selectors.selectedEditedAction],
            (tab, selectedEditedAction) => {
                if (tab === 'actions' && selectedEditedAction?.steps) {
                    return selectedEditedAction.steps
                        .map((step, index) => ({
                            element: getElementForStep(step),
                            index,
                        }))
                        .filter(e => e.element)
                }
                return []
            },
        ],

        actionElements: [
            s => [s.allActionElements, s.rectUpdateCounter, dockLogic.selectors.isAnimating],
            allActionElements =>
                allActionElements.map(element =>
                    element.element ? { ...element, rect: element.element.getBoundingClientRect() } : element
                ),
        ],

        elementMap: [
            s => [s.heatmapElements, s.inspectElements, s.actionElements],
            (heatmapElements, inspectElements, actionElements) => {
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
                actionElements.forEach(e => {
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
            s => [actionsLogic.selectors.actionsForCurrentUrl, s.rectUpdateCounter],
            actionsForCurrentUrl => {
                const actionsForElementMap = new Map()
                actionsForCurrentUrl.forEach((action, index) => {
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
                                array.push({ action, step, element, rect, index })
                            }
                        })
                })
                return actionsForElementMap
            },
        ],

        elementsWithActions: [s => [s.actionsForElementMap], actionsForElementMap => [...actionsForElementMap.keys()]],

        actionsListElements: [
            s => [s.actionsForElementMap],
            actionsForElementMap => [...actionsForElementMap.values()].map(a => a[0]),
        ],

        elementsToDisplay: [
            s => [
                s.actionElements,
                s.inspectElements,
                s.actionsListElements,
                actionsTabLogic.selectors.selectedAction,
                toolbarTabLogic.selectors.tab,
            ],
            (actionElements, inspectElements, actionsListElements, selectedAction, tab) => {
                if (inspectElements.length > 0) {
                    return inspectElements
                }
                if (tab === 'actions' && selectedAction && actionElements.length > 0) {
                    return actionElements
                }
                if (tab === 'actions' && !selectedAction && actionsListElements.length > 0) {
                    return actionsListElements
                }
                return []
            },
        ],

        labelsToDisplay: [
            s => [
                s.actionElements,
                s.actionsListElements,
                actionsTabLogic.selectors.selectedAction,
                toolbarTabLogic.selectors.tab,
            ],
            (actionElements, actionsListElements, selectedAction, tab) => {
                if (tab === 'actions' && selectedAction && actionElements.length > 0) {
                    return actionElements
                }
                if (tab === 'actions' && !selectedAction && actionsListElements.length > 0) {
                    return actionsListElements
                }
                return []
            },
        ],

        actionLabelsToDisplay: [
            s => [s.elementsWithActions, s.inspectEnabled],
            (elementsWithActions, inspectEnabled) => (inspectEnabled ? elementsWithActions : []),
        ],

        selectedElementMeta: [
            s => [s.selectedElement, s.elementMap, s.actionsForElementMap],
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
            s => [s.hoverElement, s.elementMap, s.actionsForElementMap],
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
            s => [s.highlightElement, s.elementMap, s.actionsForElementMap],
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

    listeners: ({ actions, values }) => ({
        enableInspect: () => {
            actionsLogic.actions.getActions()
        },
        selectElement: ({ element }) => {
            if (toolbarTabLogic.values.tab === 'stats') {
                actions.setSelectedElement(element)
            } else if (toolbarTabLogic.values.tab === 'actions') {
                actions.setHoverElement(null)
                if (actionsTabLogic.values.inspectingElement !== null) {
                    actionsTabLogic.actions.inspectElementSelected(element, actionsTabLogic.values.inspectingElement)
                }
                if (!actionsTabLogic.values.selectedAction) {
                    const action = values.elementsToDisplay.find(e => e.element === element)?.action
                    if (action) {
                        actionsTabLogic.actions.selectAction(action.id)
                    }
                }
            }
        },
        createAction: ({ element }) => {
            toolbarTabLogic.actions.setTab('actions')
            actionsTabLogic.actions.newAction(element)
        },
    }),
})
