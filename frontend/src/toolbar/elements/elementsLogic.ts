import { kea } from 'kea'

import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { elementToActionStep, getAllClickTargets, getElementForStep, getRectForElement } from '~/toolbar/utils'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import type { elementsLogicType } from './elementsLogicType'
import { ActionElementWithMetadata, ElementWithMetadata } from '~/toolbar/types'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { posthog } from '~/toolbar/posthog'
import { collectAllElementsDeep } from 'query-selector-shadow-dom'
import { ElementType } from '~/types'

export type ActionElementMap = Map<HTMLElement, ActionElementWithMetadata[]>
export type ElementMap = Map<HTMLElement, ElementWithMetadata>

function debounce<F extends (...args: Parameters<F>) => ReturnType<F>>(
    func: F,
    waitFor: number
): (...args: Parameters<F>) => void {
    let timeout: ReturnType<typeof setTimeout>
    return (...args: Parameters<F>): void => {
        clearTimeout(timeout)
        timeout = setTimeout(() => func(...args), waitFor)
    }
}

export const elementsLogic = kea<elementsLogicType>({
    path: ['toolbar', 'elements', 'elementsLogic'],
    actions: {
        enableInspect: true,
        disableInspect: true,

        selectElement: (element: HTMLElement | null) => ({ element }),
        createAction: (element: HTMLElement) => ({ element }),

        updateRects: true,
        setHoverElement: (element: HTMLElement | null) => ({ element }),
        setHighlightElement: (element: HTMLElement | null) => ({ element }),
        setSelectedElement: (element: HTMLElement | null) => ({ element }),

        setRelativePositionCompensation: (compensation: number) => ({ compensation }),
        overrideSelector: (element: HTMLElement, selector: string | null) => ({ element, selector }),
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
        relativePositionCompensation: [
            0,
            {
                setRelativePositionCompensation: (_, { compensation }) => compensation,
            },
        ],
        overriddenSelectors: [
            new Map<HTMLElement, string>(),
            {
                overrideSelector: (state, { element, selector }) => {
                    const newMap = new Map(state)
                    if (newMap.has(element) && !selector) {
                        newMap.delete(element)
                    } else if (!!selector) {
                        newMap.set(element, selector)
                    }
                    return newMap
                },
            },
        ],
    }),

    selectors: {
        inspectEnabled: [
            (s) => [
                s.inspectEnabledRaw,
                actionsTabLogic.selectors.inspectingElement,
                actionsTabLogic.selectors.buttonActionsVisible,
            ],
            (inpsectEnabledRaw, inspectingElement, buttonActionsVisible) =>
                inpsectEnabledRaw || (buttonActionsVisible && inspectingElement !== null),
        ],

        heatmapEnabled: [() => [heatmapLogic.selectors.heatmapEnabled], (heatmapEnabled) => heatmapEnabled],

        heatmapElements: [
            (s) => [heatmapLogic.selectors.countedElements, s.rectUpdateCounter, toolbarLogic.selectors.buttonVisible],
            (countedElements) =>
                countedElements.map((e) => ({ ...e, rect: getRectForElement(e.element) } as ElementWithMetadata)),
        ],

        allInspectElements: [
            (s) => [s.inspectEnabled, currentPageLogic.selectors.href],
            (inspectEnabled) => (inspectEnabled ? getAllClickTargets() : []),
        ],

        inspectElements: [
            (s) => [s.allInspectElements, s.rectUpdateCounter, toolbarLogic.selectors.buttonVisible],
            (allInspectElements) =>
                allInspectElements
                    .map((element) => ({ element, rect: getRectForElement(element) } as ElementWithMetadata))
                    .filter((e) => e.rect && e.rect.width * e.rect.height > 0),
        ],

        displayActionElements: [
            () => [actionsTabLogic.selectors.buttonActionsVisible],
            (buttonActionsVisible) => buttonActionsVisible,
        ],

        allActionElements: [
            (s) => [s.displayActionElements, actionsTabLogic.selectors.selectedEditedAction],
            (displayActionElements, selectedEditedAction): ElementWithMetadata[] => {
                if (displayActionElements && selectedEditedAction?.steps) {
                    const allElements = collectAllElementsDeep('*', document)
                    const steps: ElementWithMetadata[] = []
                    selectedEditedAction.steps.forEach((step, index) => {
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
            (s) => [s.allActionElements, s.rectUpdateCounter, toolbarLogic.selectors.buttonVisible],
            (allActionElements) =>
                allActionElements.map((element) =>
                    element.element ? { ...element, rect: getRectForElement(element.element) } : element
                ),
        ],

        elementMap: [
            (s) => [
                s.heatmapElements,
                s.inspectElements,
                s.actionElements,
                s.actionsListElements,
                s.overriddenSelectors,
            ],
            (heatmapElements, inspectElements, actionElements, actionsListElements, overridenSelectors): ElementMap => {
                console.log('building element map', overridenSelectors)
                const elementMap = new Map<HTMLElement, ElementWithMetadata>()

                inspectElements.forEach((e) => {
                    updateElementMap(overridenSelectors, e, elementMap)
                })
                heatmapElements.forEach((e) => {
                    updateElementMap(overridenSelectors, e, elementMap)
                })
                ;[...actionElements, ...actionsListElements].forEach((e) => {
                    updateElementMap(overridenSelectors, e, elementMap)
                })
                return elementMap
            },
        ],

        actionsForElementMap: [
            (s) => [actionsLogic.selectors.sortedActions, s.rectUpdateCounter, toolbarLogic.selectors.buttonVisible],
            (sortedActions): ActionElementMap => {
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
            (s) => [s.selectedElement, s.elementMap, s.actionsForElementMap, toolbarLogic.selectors.dataAttributes],
            (selectedElement, elementMap, actionsForElementMap, dataAttributes) => {
                if (selectedElement) {
                    const meta = elementMap.get(selectedElement)
                    if (meta) {
                        const actions = actionsForElementMap.get(selectedElement)
                        return {
                            ...meta,
                            actionStep: elementToActionStep(meta.element, dataAttributes, meta.overriddenSelector),
                            actions: actions || [],
                        }
                    }
                }
                return null
            },
        ],

        hoverElementMeta: [
            (s) => [s.hoverElement, s.elementMap, s.actionsForElementMap, toolbarLogic.selectors.dataAttributes],
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
            (s) => [s.highlightElement, s.elementMap, s.actionsForElementMap, toolbarLogic.selectors.dataAttributes],
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
                const activeMeta = selectedElementMeta || hoverElementMeta
                console.log('activeMeta', activeMeta, 'has overridden selector: ', !!activeMeta?.selector)
                return activeMeta
            },
        ],
        activeElementChain: [
            (s) => [s.activeMeta],
            (activeMeta): ElementType[] => {
                const chain: HTMLElement[] = []
                let currentElement: HTMLElement | null | undefined = activeMeta?.element
                while (currentElement && chain.length <= 10 && currentElement !== document.body) {
                    chain.push(currentElement)
                    currentElement = currentElement.parentElement
                }
                const elements = chain.map(
                    (element, index) =>
                        ({
                            attr_class: element.getAttribute('class') || undefined,
                            attr_id: element.getAttribute('id') || undefined,
                            attributes: Array.from(element.attributes).reduce((acc, attr) => {
                                if (!acc[attr.name]) {
                                    acc[attr.name] = attr.value
                                } else {
                                    acc[attr.name] += ` ${attr.value}`
                                }
                                return acc
                            }, {} as Record<string, string>),
                            href: element.getAttribute('href') || undefined,
                            tag_name: element.tagName.toLowerCase(),
                            text: index === 0 ? element.innerText : undefined,
                        } as ElementType)
                )

                return elements
            },
        ],
    },

    events: ({ cache, values, actions }) => ({
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
            cache.onClick = () => actions.updateRects()
            cache.onScrollResize = () => {
                window.clearTimeout(cache.clickDelayTimeout)
                actions.updateRects()
                cache.clickDelayTimeout = window.setTimeout(actions.updateRects, 100)
                cache.updateRelativePosition()
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
            cache.updateRelativePosition()
        },
        beforeUnmount: () => {
            window.removeEventListener('click', cache.onClick)
            window.removeEventListener('resize', cache.onScrollResize)
            window.removeEventListener('keydown', cache.onKeyDown)
            window.document.removeEventListener('scroll', cache.onScrollResize, true)
        },
    }),

    listeners: ({ actions, values }) => ({
        enableInspect: () => {
            posthog.capture('toolbar mode triggered', { mode: 'inspect', enabled: true })
            actionsLogic.actions.getActions()
        },
        disableInspect: () => {
            posthog.capture('toolbar mode triggered', { mode: 'inspect', enabled: false })
        },
        selectElement: ({ element }) => {
            const inspectForAction =
                actionsTabLogic.values.buttonActionsVisible && actionsTabLogic.values.inspectingElement !== null

            if (inspectForAction) {
                actions.setHoverElement(null)
                if (element) {
                    actionsTabLogic.actions.inspectElementSelected(element, actionsTabLogic.values.inspectingElement)
                }
            } else {
                actions.setSelectedElement(element)
            }

            const { inspectEnabled, heatmapEnabled, enabledLast, selectedElementMeta } = values
            const { buttonActionsVisible: actionsEnabled } = actionsTabLogic.values

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

            posthog.capture('toolbar selected HTML element', {
                element_tag: element?.tagName.toLowerCase(),
                element_type: (element as HTMLInputElement)?.type,
                has_href: !!(element as HTMLAnchorElement)?.href,
                has_class: !!element?.className,
                has_id: !!element?.id,
                has_name: !!(element as HTMLInputElement)?.name,
                has_data_attr: data_attributes.includes('data-attr'),
                data_attributes: data_attributes,
                attribute_length: element?.attributes.length,
                inspect_enabled: inspectEnabled,
                heatmap_enabled: heatmapEnabled,
                actions_enabled: actionsEnabled,
                enabled_last: enabledLast,
                heatmap_count: heatmapEnabled ? selectedElementMeta?.count || 0 : undefined,
                actions_count: actionsEnabled ? selectedElementMeta?.actions.length : undefined,
            })
        },
        createAction: ({ element }) => {
            actionsTabLogic.actions.showButtonActions()
            toolbarButtonLogic.actions.showActionsInfo()
            elementsLogic.actions.selectElement(null)
            actionsTabLogic.actions.newAction(element)
        },
    }),
})

/**
 *  Yuck warning: this relies on the instance identify of elementMap
 * it's already expensive enough passing around and serialising the elements in the map
 * let's not make it worse by cloning the map every time we update it
 *
 */
function updateElementMap(
    overridenSelectors: Map<HTMLElement, string>,
    e: ElementWithMetadata,
    elementMap: Map<HTMLElement, ElementWithMetadata>
): void {
    const elementWithMetadata: ElementWithMetadata = overridenSelectors.has(e.element)
        ? { ...e, overriddenSelector: overridenSelectors.get(e.element) }
        : { ...e }
    if (elementMap.get(e.element)) {
        elementMap.set(e.element, { ...elementMap.get(e.element), ...elementWithMetadata })
    } else {
        elementMap.set(e.element, elementWithMetadata)
    }
}
