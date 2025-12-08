import { JSONContent } from '@tiptap/core'
import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { subscriptions } from 'kea-subscriptions'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { ElementRect } from '~/toolbar/types'
import { TOOLBAR_ID, elementToActionStep, getRectForElement } from '~/toolbar/utils'

import type { productToursLogicType } from './productToursLogicType'

export interface TourStep {
    selector: string
    content: JSONContent | null
    element?: HTMLElement
}

export interface TourForm {
    name: string
    steps: TourStep[]
}

function newTour(): TourForm {
    return {
        name: '',
        steps: [],
    }
}

function isToolbarElement(element: HTMLElement): boolean {
    const toolbar = document.getElementById(TOOLBAR_ID)
    return toolbar?.contains(element) ?? false
}

export const productToursLogic = kea<productToursLogicType>([
    path(['toolbar', 'product-tours', 'productToursLogic']),

    actions({
        showButtonProductTours: true,
        hideButtonProductTours: true,
        inspectForElementWithIndex: (index: number | null) => ({ index }),
        editStep: (index: number) => ({ index }),
        selectElement: (element: HTMLElement) => ({ element }),
        confirmStep: (content: JSONContent | null) => ({ content }),
        cancelStep: true,
        selectTour: (id: number | null) => ({ id }),
        newTour: true,
        addStep: true,
        removeStep: (index: number) => ({ index }),
        setHoverElement: (element: HTMLElement | null) => ({ element }),
        updateRects: true,
    }),

    reducers({
        buttonProductToursVisible: [
            false,
            {
                showButtonProductTours: () => true,
                hideButtonProductTours: () => false,
            },
        ],
        selectedTourId: [
            null as number | 'new' | null,
            {
                selectTour: (_, { id }) => id,
                newTour: () => 'new',
            },
        ],
        inspectingElement: [
            null as number | null,
            {
                inspectForElementWithIndex: (_, { index }) => index,
                editStep: (_, { index }) => index,
                inspectElementSelected: () => null,
                selectTour: () => null,
                newTour: () => null,
                hideButtonProductTours: () => null,
            },
        ],
        hoverElement: [
            null as HTMLElement | null,
            {
                setHoverElement: (_, { element }) => element,
                selectElement: () => null,
                confirmStep: () => null,
                cancelStep: () => null,
                inspectForElementWithIndex: () => null,
                hideButtonProductTours: () => null,
            },
        ],
        selectedElement: [
            null as HTMLElement | null,
            {
                selectElement: (_, { element }) => element,
                cancelStep: () => null,
                inspectForElementWithIndex: () => null,
                hideButtonProductTours: () => null,
            },
        ],
        rectUpdateCounter: [
            0,
            {
                updateRects: (state) => state + 1,
            },
        ],
    }),

    forms(() => ({
        tourForm: {
            defaults: { name: '', steps: [] } as TourForm,
            errors: ({ name }) => ({
                name: !name || !name.length ? 'Must name this tour' : undefined,
            }),
            submit: async () => {
                // No persistence in this phase - just log for now
            },
        },
    })),

    connect(() => ({
        values: [toolbarConfigLogic, ['dataAttributes']],
    })),

    selectors({
        selectedTour: [
            (s) => [s.selectedTourId],
            (selectedTourId): TourForm | null => {
                if (selectedTourId === 'new') {
                    return newTour()
                }
                return null
            },
        ],
        isInspecting: [
            (s) => [s.inspectingElement, s.selectedTourId],
            (inspectingElement, selectedTourId) => selectedTourId !== null && inspectingElement !== null,
        ],
        hoverElementRect: [
            (s) => [s.hoverElement, s.rectUpdateCounter],
            (hoverElement): ElementRect | null => {
                if (!hoverElement) {
                    return null
                }
                return getRectForElement(hoverElement)
            },
        ],
        selectedElementRect: [
            (s) => [s.selectedElement, s.rectUpdateCounter],
            (selectedElement): ElementRect | null => {
                if (!selectedElement) {
                    return null
                }
                return getRectForElement(selectedElement)
            },
        ],
        isEditingStep: [(s) => [s.selectedElement], (selectedElement) => selectedElement !== null],
        editingStep: [
            (s) => [s.inspectingElement, s.tourForm],
            (inspectingElement, tourForm): TourStep | null => {
                if (inspectingElement === null) {
                    return null
                }
                return tourForm?.steps?.[inspectingElement] ?? null
            },
        ],
    }),

    subscriptions(({ actions }) => ({
        selectedTour: (selectedTour: TourForm | null) => {
            if (!selectedTour) {
                actions.resetTourForm()
            } else {
                actions.setTourFormValue('name', selectedTour.name)
                actions.setTourFormValue('steps', selectedTour.steps)
            }
        },
    })),

    listeners(({ actions, values }) => ({
        confirmStep: ({ content }) => {
            if (values.tourForm && values.selectedElement) {
                const actionStep = elementToActionStep(values.selectedElement, values.dataAttributes)
                const selector = actionStep.selector || ''

                const newStep: TourStep = {
                    selector,
                    content,
                    element: values.selectedElement,
                }

                const steps = [...(values.tourForm.steps || [])]
                const index = values.inspectingElement

                if (index !== null && index < steps.length) {
                    steps[index] = newStep
                } else {
                    steps.push(newStep)
                }

                actions.setTourFormValue('steps', steps)
                actions.inspectForElementWithIndex(null)
            }
        },
        editStep: ({ index }) => {
            const step = values.tourForm?.steps?.[index]
            if (step?.element && document.body.contains(step.element)) {
                actions.selectElement(step.element)
            }
            // If element not in DOM, reducer already set inspectingElement
            // so user will be in selection mode to pick a new element
        },
        addStep: () => {
            const nextIndex = values.tourForm?.steps?.length ?? 0
            actions.inspectForElementWithIndex(nextIndex)
        },
        removeStep: ({ index }) => {
            if (values.tourForm) {
                const steps = [...(values.tourForm.steps || [])]
                steps.splice(index, 1)
                actions.setTourFormValue('steps', steps)
            }
        },
        newTour: () => {
            // Close the sidebar menu when starting to edit a tour
            toolbarLogic.actions.setVisibleMenu('none')
        },
        showButtonProductTours: () => {
            toolbarPosthogJS.capture('toolbar mode triggered', { mode: 'product-tours', enabled: true })
        },
        hideButtonProductTours: () => {
            toolbarPosthogJS.capture('toolbar mode triggered', { mode: 'product-tours', enabled: false })
        },
    })),

    events(({ actions, values, cache }) => ({
        afterMount: () => {
            cache.onMouseOver = (e: MouseEvent): void => {
                if (!values.isInspecting) {
                    return
                }
                const target = e.target as HTMLElement
                if (target && !isToolbarElement(target)) {
                    actions.setHoverElement(target)
                }
            }

            cache.onClick = (e: MouseEvent): void => {
                if (!values.isInspecting || values.isEditingStep) {
                    return
                }
                const target = e.target as HTMLElement
                if (target && !isToolbarElement(target)) {
                    e.preventDefault()
                    e.stopPropagation()
                    actions.selectElement(target)
                }
            }

            cache.onScroll = (): void => {
                if (values.hoverElement || values.selectedElement) {
                    actions.updateRects()
                }
            }

            cache.onResize = (): void => {
                if (values.hoverElement || values.selectedElement) {
                    actions.updateRects()
                }
            }

            cache.onKeyDown = (e: KeyboardEvent): void => {
                if (e.key === 'Escape' && values.isInspecting) {
                    actions.inspectForElementWithIndex(null)
                    actions.setHoverElement(null)
                }
            }

            document.addEventListener('mouseover', cache.onMouseOver, true)
            document.addEventListener('click', cache.onClick, true)
            document.addEventListener('scroll', cache.onScroll, true)
            window.addEventListener('resize', cache.onResize)
            window.addEventListener('keydown', cache.onKeyDown)
        },
        beforeUnmount: () => {
            if (cache.onMouseOver) {
                document.removeEventListener('mouseover', cache.onMouseOver, true)
            }
            if (cache.onClick) {
                document.removeEventListener('click', cache.onClick, true)
            }
            if (cache.onScroll) {
                document.removeEventListener('scroll', cache.onScroll, true)
            }
            if (cache.onResize) {
                window.removeEventListener('resize', cache.onResize)
            }
            if (cache.onKeyDown) {
                window.removeEventListener('keydown', cache.onKeyDown)
            }
        },
    })),
])
