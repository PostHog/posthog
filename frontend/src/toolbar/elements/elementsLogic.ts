import { kea } from 'kea'

import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { elementToActionStep, getAllClickTargets, getElementForStep, getRectForElement } from '~/toolbar/utils'
import { dockLogic } from '~/toolbar/dockLogic'
import { toolbarTabLogic } from '~/toolbar/toolbarTabLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { elementsLogicType } from 'types/toolbar/elements/elementsLogicType'
import { ActionStepType, ActionType, ToolbarMode, ToolbarTab } from '~/types'
import { ActionElementWithMetadata, ActionForm, ElementWithMetadata } from '~/toolbar/types'

type ActionElementMap = Map<HTMLElement, ActionElementWithMetadata[]>
type ElementMap = Map<HTMLElement, ElementWithMetadata>

export const elementsLogic = kea<
    elementsLogicType<
        ToolbarTab,
        ToolbarMode,
        ActionStepType,
        ActionForm,
        ActionType,
        ElementWithMetadata,
        ActionElementWithMetadata,
        ActionElementMap,
        ElementMap
    >
>({
    actions: {
        enableInspect: true,
        disableInspect: true,

        selectElement: (element: HTMLElement | null) => ({ element }),
        createAction: (element: HTMLElement) => ({ element }),

        updateRects: true,
        setHoverElement: (element: HTMLElement | null) => ({ element }),
        setHighlightElement: (element: HTMLElement | null) => ({ element }),
        setSelectedElement: (element: HTMLElement | null) => ({ element }),
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
        hoverElement: [
            null as HTMLElement | null,
            {
                setHoverElement: (_, { element }) => element,
                enableInspect: () => null,
                disableInspect: () => null,
                createAction: () => null,
                [toolbarTabLogic.actionTypes.setTab]: () => null,
            },
        ],
        highlightElement: [
            null as HTMLElement | null,
            {
                setHighlightElement: (_, { element }) => element,
                setHoverElement: () => null,
                setSelectedElement: () => null,
                selectElement: () => null,
                disableInspect: () => null,
                createAction: () => null,
                [toolbarTabLogic.actionTypes.setTab]: () => null,
            },
        ],
        selectedElement: [
            null as HTMLElement | null,
            {
                setSelectedElement: (_, { element }) => element,
                disableInspect: () => null,
                createAction: () => null,
                [toolbarTabLogic.actionTypes.setTab]: () => null,
                [heatmapLogic.actionTypes.disableHeatmap]: () => null,
                [actionsTabLogic.actionTypes.selectAction]: () => null,
            },
        ],
        enabledLast: [
            null as null | 'inspect' | 'heatmap',
            {
                // keep track of what to disable first with ESC
                enableInspect: () => 'inspect',
                [heatmapLogic.actionTypes.enableHeatmap]: () => 'heatmap',
            },
        ],
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
            (countedElements) =>
                countedElements.map((e) => ({ ...e, rect: getRectForElement(e.element) } as ElementWithMetadata)),
        ],

        allInspectElements: [
            (s) => [s.inspectEnabled],
            (inspectEnabled) => (inspectEnabled ? getAllClickTargets() : []),
        ],

        inspectElements: [
            (s) => [s.allInspectElements, s.rectUpdateCounter, dockLogic.selectors.isAnimating],
            (allInspectElements) =>
                allInspectElements
                    .map((element) => ({ element, rect: getRectForElement(element) } as ElementWithMetadata))
                    .filter((e) => e.rect && e.rect.width * e.rect.height > 0),
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
            (displayActionElements, selectedEditedAction): ElementWithMetadata[] => {
                if (displayActionElements && selectedEditedAction?.steps) {
                    const steps: ElementWithMetadata[] = []
                    selectedEditedAction.steps.forEach((step, index) => {
                        const element = getElementForStep(step)
                        if (element) {
                            steps.push({
                                element,
                                index,
                            })
                        }
                    })
                }
                return [] as ElementWithMetadata[]
            },
        ],

        actionElements: [
            (s) => [s.allActionElements, s.rectUpdateCounter, dockLogic.selectors.isAnimating],
            (allActionElements) =>
                allActionElements.map((element) =>
                    element.element ? { ...element, rect: getRectForElement(element.element) } : element
                ),
        ],

        elementMap: [
            (s) => [s.heatmapElements, s.inspectElements, s.actionElements, s.actionsListElements],
            (heatmapElements, inspectElements, actionElements, actionsListElements): ElementMap => {
                const elementMap = new Map<HTMLElement, ElementWithMetadata>()

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
            (s) => [actionsLogic.selectors.sortedActions, s.rectUpdateCounter, dockLogic.selectors.isAnimating],
            (sortedActions): ActionElementMap => {
                const actionsForElementMap = new Map<HTMLElement, ActionElementWithMetadata[]>()
                sortedActions.forEach((action, index) => {
                    action.steps
                        ?.filter((step) => step.event === '$autocapture')
                        .forEach((step) => {
                            const element = getElementForStep(step)
                            if (element) {
                                const rect = getRectForElement(element)
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
            (actionsForElementMap) => [...((actionsForElementMap.keys() as unknown) as HTMLElement[])],
        ],

        actionsListElements: [
            (s) => [s.actionsForElementMap],
            (actionsForElementMap) =>
                [...((actionsForElementMap.values() as unknown) as ActionElementWithMetadata[][])].map((a) => a[0]),
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
                return elementsToDisplayRaw.filter(({ rect }) => rect && (rect.width !== 0 || rect.height !== 0))
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

        selectedElementMeta: [
            (s) => [s.selectedElement, s.elementMap, s.actionsForElementMap],
            (selectedElement, elementMap, actionsForElementMap) => {
                if (selectedElement) {
                    const meta = elementMap.get(selectedElement)
                    if (meta) {
                        const actions = actionsForElementMap.get(selectedElement)
                        return {
                            ...meta,
                            actionStep: elementToActionStep(meta.element),
                            actions: actions || [],
                        }
                    }
                }
                return null
            },
        ],

        hoverElementMeta: [
            (s) => [s.hoverElement, s.elementMap, s.actionsForElementMap],
            (hoverElement, elementMap, actionsForElementMap) => {
                if (hoverElement) {
                    const meta = elementMap.get(hoverElement)
                    if (meta) {
                        const actions = actionsForElementMap.get(hoverElement)
                        return {
                            ...meta,
                            actionStep: elementToActionStep(meta.element),
                            actions: actions || [],
                        }
                    }
                }
                return null
            },
        ],

        highlightElementMeta: [
            (s) => [s.highlightElement, s.elementMap, s.actionsForElementMap],
            (highlightElement, elementMap, actionsForElementMap) => {
                if (highlightElement) {
                    const meta = elementMap.get(highlightElement)
                    if (meta) {
                        const actions = actionsForElementMap.get(highlightElement)
                        return {
                            ...meta,
                            actionStep: elementToActionStep(meta.element),
                            actions: actions || [],
                        }
                    }
                }
                return null
            },
        ],
    },

    events: ({ cache, values, actions }) => ({
        afterMount: () => {
            cache.onClick = () => actions.updateRects()
            cache.onScrollResize = () => {
                window.clearTimeout(cache.clickDelayTimeout)
                actions.updateRects()
                cache.clickDelayTimeout = window.setTimeout(actions.updateRects, 100)
            }
            cache.onKeyDown = (e: KeyboardEvent) => {
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
                if (element) {
                    actionsTabLogic.actions.inspectElementSelected(element, actionsTabLogic.values.inspectingElement)
                }
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
