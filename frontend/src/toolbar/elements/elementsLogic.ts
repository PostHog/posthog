import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { collectAllElementsDeep } from 'query-selector-shadow-dom'

import { EXPERIMENT_TARGET_SELECTOR } from 'lib/actionUtils'
import { debounce } from 'lib/utils'

import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { experimentsTabLogic } from '~/toolbar/experiments/experimentsTabLogic'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { ActionElementWithMetadata, ElementWithMetadata } from '~/toolbar/types'

import { elementToActionStep, getAllClickTargets, getElementForStep, getRectForElement } from '../utils'
import type { elementsLogicType } from './elementsLogicType'
import { heatmapToolbarMenuLogic } from './heatmapToolbarMenuLogic'

export type ActionElementMap = Map<HTMLElement, ActionElementWithMetadata[]>
export type ElementMap = Map<HTMLElement, ElementWithMetadata>

const getMaxZIndex = (element: Element): number => {
    let maxZIndex = 0
    let currentElement: Element | null = element

    while (currentElement) {
        const zIndex = parseInt(getComputedStyle(currentElement).zIndex)
        if (!isNaN(zIndex) && zIndex > maxZIndex) {
            maxZIndex = zIndex
        }
        currentElement = currentElement.parentElement
    }

    return maxZIndex
}

export const elementsLogic = kea<elementsLogicType>([
    path(['toolbar', 'elements', 'elementsLogic']),

    connect(() => ({
        values: [actionsTabLogic, ['actionForm'], currentPageLogic, ['href']],
        actions: [actionsTabLogic, ['selectAction', 'newAction']],
    })),
    actions({
        enableInspect: true,
        disableInspect: true,

        selectElement: (element: HTMLElement | null) => ({
            element,
        }),
        createAction: (element: HTMLElement) => ({ element }),

        updateRects: true,
        setHoverElement: (element: HTMLElement | null) => ({ element }),
        setHighlightElement: (element: HTMLElement | null) => ({ element }),
        setSelectedElement: (element: HTMLElement | null) => ({ element }),

        setRelativePositionCompensation: (compensation: number) => ({ compensation }),
    }),
    reducers(() => ({
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
                selectElement: () => null,
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
            },
        ],
        selectedElement: [
            null as HTMLElement | null,
            {
                setSelectedElement: (_, { element }) => element,
                disableInspect: () => null,
                createAction: () => null,
                [heatmapToolbarMenuLogic.actionTypes.disableHeatmap]: () => null,
                selectAction: () => null,
            },
        ],
        enabledLast: [
            null as null | 'inspect' | 'heatmap',
            {
                // keep track of what to disable first with ESC
                enableInspect: () => 'inspect',
                [heatmapToolbarMenuLogic.actionTypes.enableHeatmap]: () => 'heatmap',
            },
        ],
        relativePositionCompensation: [
            0,
            {
                setRelativePositionCompensation: (_, { compensation }) => compensation,
            },
        ],
    })),
    selectors({
        activeMetaIsSelected: [
            (s) => [s.selectedElementMeta, s.activeMeta],
            (selectedElementMeta, activeMeta) => {
                return !!selectedElementMeta && !!activeMeta && selectedElementMeta.element === activeMeta.element
            },
        ],
        inspectEnabled: [
            (s) => [
                s.inspectEnabledRaw,
                actionsTabLogic.selectors.inspectingElement,
                actionsTabLogic.selectors.buttonActionsVisible,
                experimentsTabLogic.selectors.inspectingElement,
            ],
            (
                inspectEnabledRaw,
                actionsInspectingElement,
                actionsButtonActionsVisible,
                experimentsInspectingElement
            ) => {
                return (
                    inspectEnabledRaw ||
                    (actionsButtonActionsVisible && actionsInspectingElement !== null) ||
                    experimentsInspectingElement !== null
                )
            },
        ],

        heatmapEnabled: [() => [heatmapToolbarMenuLogic.selectors.heatmapEnabled], (heatmapEnabled) => heatmapEnabled],

        heatmapElements: [
            (s) => [
                heatmapToolbarMenuLogic.selectors.countedElements,
                s.rectUpdateCounter,
                toolbarConfigLogic.selectors.buttonVisible,
            ],
            (countedElements) =>
                countedElements.map(
                    (e) =>
                        ({
                            ...e,
                            rect: getRectForElement(e.element),
                        }) as ElementWithMetadata
                ),
        ],

        allInspectElements: [
            (s) => [s.inspectEnabled, s.href],
            (inspectEnabled) => {
                if (!inspectEnabled) {
                    return []
                }
                const inspectForExperiment =
                    experimentsTabLogic.values.buttonExperimentsVisible &&
                    experimentsTabLogic.values.inspectingElement !== null
                const selector = inspectForExperiment
                    ? experimentsTabLogic.values.elementSelector || EXPERIMENT_TARGET_SELECTOR
                    : undefined
                return getAllClickTargets(undefined, selector)
            },
        ],

        inspectElements: [
            (s) => [s.allInspectElements, s.rectUpdateCounter, toolbarConfigLogic.selectors.buttonVisible],
            (allInspectElements) =>
                allInspectElements
                    .map(
                        (element) =>
                            ({
                                element,
                                rect: getRectForElement(element),
                            }) as ElementWithMetadata
                    )
                    .filter((e) => e.rect && e.rect.width * e.rect.height > 0),
        ],

        displayActionElements: [
            () => [actionsTabLogic.selectors.buttonActionsVisible],
            (buttonActionsVisible) => {
                return buttonActionsVisible
            },
        ],

        _actionElements: [
            (s) => [s.displayActionElements, s.actionForm],
            (displayActionElements, actionForm): ElementWithMetadata[] => {
                // This function is expensive so should be calculated as rarely as possible
                if (displayActionElements && actionForm?.steps) {
                    const allElements = collectAllElementsDeep('*', document)
                    const steps: ElementWithMetadata[] = []
                    actionForm.steps.forEach((step, index) => {
                        const element = getElementForStep(step, allElements)
                        if (element) {
                            steps.push({
                                element,
                                index,
                            })
                        }
                    })
                    return steps
                }
                return [] as ElementWithMetadata[]
            },
        ],

        actionElements: [
            (s) => [s._actionElements, s.rectUpdateCounter, toolbarConfigLogic.selectors.buttonVisible],
            (actionElements) =>
                actionElements.map((element) =>
                    element.element ? { ...element, rect: getRectForElement(element.element) } : element
                ),
        ],

        elementMap: [
            (s) => [s.heatmapElements, s.inspectElements, s.actionElements, s.actionsListElements],
            (heatmapElements, inspectElements, actionElements, actionsListElements): ElementMap => {
                const elementMap = new Map<HTMLElement, ElementWithMetadata>()

                const addElements = (e: ElementWithMetadata): void => {
                    const elementWithMetadata: ElementWithMetadata = { ...e }
                    if (elementMap.get(e.element)) {
                        elementMap.set(e.element, { ...elementMap.get(e.element), ...elementWithMetadata })
                    } else {
                        elementMap.set(e.element, elementWithMetadata)
                    }
                }

                inspectElements.forEach(addElements)
                heatmapElements.forEach(addElements)
                actionElements.forEach(addElements)
                actionsListElements.forEach(addElements)

                return elementMap
            },
        ],

        _actionsForElementMap: [
            () => [actionsLogic.selectors.sortedActions],
            (sortedActions): ActionElementMap => {
                // This function is expensive so should be calculated as rarely as possible
                const allElements = collectAllElementsDeep('*', document)
                const actionsForElementMap = new Map<HTMLElement, ActionElementWithMetadata[]>()
                sortedActions.forEach((action, index) => {
                    action.steps
                        ?.filter((step) => step.event === '$autocapture')
                        .forEach((step) => {
                            const element = getElementForStep(step, allElements)
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

        actionsForElementMap: [
            (s) => [s._actionsForElementMap, s.rectUpdateCounter, toolbarConfigLogic.selectors.buttonVisible],
            (actionsForElementMap): ActionElementMap => {
                // We recalculate the rects here to avoid calling the expensive getElementForStep
                actionsForElementMap.forEach((actions, element) => {
                    actions.forEach((action) => {
                        action.rect = getRectForElement(element)
                    })
                })

                return actionsForElementMap
            },
        ],

        elementsWithActions: [
            (s) => [s.actionsForElementMap],
            (actionsForElementMap) => [...(actionsForElementMap.keys() as unknown as HTMLElement[])],
        ],

        actionsListElements: [
            (s) => [s.actionsForElementMap],
            (actionsForElementMap) =>
                [...(actionsForElementMap.values() as unknown as ActionElementWithMetadata[][])].map((a) => a[0]),
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
                const result: ElementWithMetadata[] = []
                elementsToDisplayRaw.forEach((element) => {
                    const { rect, visible } = element
                    // visible when undefined is ignored
                    if (rect && rect.width > 0 && rect.height > 0 && visible !== false) {
                        result.push({
                            ...element,
                            // being able to hover over elements might rely on their original z-index
                            // so we copy it over to the toolbar element
                            apparentZIndex: getMaxZIndex(element.element),
                        })
                    }
                })

                return result
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
            (s) => [
                s.selectedElement,
                s.elementMap,
                s.actionsForElementMap,
                toolbarConfigLogic.selectors.dataAttributes,
            ],
            (selectedElement, elementMap, actionsForElementMap, dataAttributes) => {
                if (selectedElement) {
                    const meta = elementMap.get(selectedElement)
                    if (meta) {
                        const actions = actionsForElementMap.get(selectedElement)
                        return {
                            ...meta,
                            actionStep: elementToActionStep(meta.element, dataAttributes),
                            actions: actions || [],
                        }
                    }
                }
                return null
            },
        ],

        hoverElementMeta: [
            (s) => [s.hoverElement, s.elementMap, s.actionsForElementMap, toolbarConfigLogic.selectors.dataAttributes],
            (hoverElement, elementMap, actionsForElementMap, dataAttributes) => {
                if (hoverElement) {
                    const meta = elementMap.get(hoverElement)
                    if (meta) {
                        const actions = actionsForElementMap.get(hoverElement)
                        return {
                            ...meta,
                            actionStep: elementToActionStep(meta.element, dataAttributes),
                            actions: actions || [],
                        }
                    }
                }
                return null
            },
        ],

        highlightElementMeta: [
            (s) => [
                s.highlightElement,
                s.elementMap,
                s.actionsForElementMap,
                toolbarConfigLogic.selectors.dataAttributes,
            ],
            (highlightElement, elementMap, actionsForElementMap, dataAttributes) => {
                if (highlightElement) {
                    const meta = elementMap.get(highlightElement)
                    if (meta) {
                        const actions = actionsForElementMap.get(highlightElement)
                        return {
                            ...meta,
                            actionStep: elementToActionStep(meta.element, dataAttributes),
                            actions: actions || [],
                        }
                    }
                }
                return null
            },
        ],
        activeMeta: [
            (s) => [s.selectedElementMeta, s.hoverElementMeta],
            (selectedElementMeta, hoverElementMeta) => {
                return selectedElementMeta || hoverElementMeta
            },
        ],
    }),
    listeners(({ actions }) => ({
        enableInspect: () => {
            toolbarPosthogJS.capture('toolbar mode triggered', { mode: 'inspect', enabled: true })
            actionsLogic.actions.getActions()
        },
        disableInspect: () => {
            toolbarPosthogJS.capture('toolbar mode triggered', { mode: 'inspect', enabled: false })
        },
        selectElement: ({ element }) => {
            const inspectForAction =
                actionsTabLogic.values.buttonActionsVisible && actionsTabLogic.values.inspectingElement !== null

            const inspectForExperiment =
                experimentsTabLogic.values.buttonExperimentsVisible &&
                experimentsTabLogic.values.inspectingElement !== null

            if (inspectForAction) {
                actions.setHoverElement(null)
                if (element) {
                    actionsTabLogic.actions.inspectElementSelected(element, actionsTabLogic.values.inspectingElement)
                }
            } else {
                actions.setSelectedElement(element)
            }

            if (inspectForExperiment) {
                actions.setHoverElement(null)
                if (element) {
                    experimentsTabLogic.actions.inspectElementSelected(
                        element,
                        experimentsTabLogic.values.selectedVariant,
                        experimentsTabLogic.values.inspectingElement
                    )
                }
            }

            // Get list of data-* attributes in the element
            const data_attributes = []
            if (element?.attributes) {
                for (let i = 0; i < element.attributes.length; i++) {
                    const name = element.attributes.item(i)?.nodeName
                    if (name && name.indexOf('data-') > -1) {
                        data_attributes.push(name)
                    }
                }
            }

            toolbarPosthogJS.capture('toolbar selected HTML element', {
                element_tag: element?.tagName.toLowerCase() ?? null,
                element_type: (element as HTMLInputElement)?.type ?? null,
                has_href: !!(element as HTMLAnchorElement)?.href,
                has_class: !!element?.className,
                has_id: !!element?.id,
                has_name: !!(element as HTMLInputElement)?.name,
                has_data_attr: data_attributes.includes('data-attr'),
                data_attributes: data_attributes,
                attribute_length: element?.attributes.length ?? null,
            })
        },
        createAction: ({ element }) => {
            actions.selectElement(null)
            // this just sets the action form
            actions.newAction(element)
        },
    })),
    events(({ cache, values, actions }) => ({
        afterMount: () => {
            cache.updateRelativePosition = debounce(() => {
                const relativePositionCompensation =
                    window.getComputedStyle(document.body).position === 'relative'
                        ? document.documentElement.getBoundingClientRect().y - document.body.getBoundingClientRect().y
                        : 0
                if (relativePositionCompensation !== values.relativePositionCompensation) {
                    actions.setRelativePositionCompensation(relativePositionCompensation)
                }
            }, 100)
            // Add event listeners using disposables
            cache.disposables.add(() => {
                const onClick = (): void => actions.updateRects()
                window.addEventListener('click', onClick)
                return () => window.removeEventListener('click', onClick)
            }, 'clickListener')

            const onScrollResize = (): void => {
                // Clear any existing timeout
                cache.disposables.dispose('clickDelayTimeout')
                actions.updateRects()

                // Add new timeout
                cache.disposables.add(() => {
                    const timeout = window.setTimeout(actions.updateRects, 100)
                    return () => window.clearTimeout(timeout)
                }, 'clickDelayTimeout')

                cache.updateRelativePosition()
            }

            cache.disposables.add(() => {
                window.addEventListener('resize', onScrollResize)
                return () => window.removeEventListener('resize', onScrollResize)
            }, 'resizeListener')

            cache.disposables.add(() => {
                const onKeyDown = (e: KeyboardEvent): void => {
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
                        heatmapToolbarMenuLogic.actions.disableHeatmap()
                        return
                    }
                    if (values.inspectEnabled) {
                        actions.disableInspect()
                        return
                    }
                    if (values.heatmapEnabled) {
                        heatmapToolbarMenuLogic.actions.disableHeatmap()
                        return
                    }
                }
                window.addEventListener('keydown', onKeyDown)
                return () => window.removeEventListener('keydown', onKeyDown)
            }, 'keydownListener')

            cache.disposables.add(() => {
                window.document.addEventListener('scroll', onScrollResize, true)
                return () => window.document.removeEventListener('scroll', onScrollResize, true)
            }, 'scrollListener')
            cache.updateRelativePosition()
        },
    })),
])
