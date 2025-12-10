import { JSONContent } from '@tiptap/core'
import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { uuid } from 'lib/utils'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { ElementRect } from '~/toolbar/types'
import { TOOLBAR_ID, elementToActionStep, getRectForElement } from '~/toolbar/utils'
import { ProductTour } from '~/types'

import type { productToursLogicType } from './productToursLogicType'

export interface TourStep {
    id: string
    selector: string
    content: JSONContent | null
    /** Local-only: reference to DOM element, not persisted */
    element?: HTMLElement
}

export interface TourForm {
    id?: string
    name: string
    steps: TourStep[]
}

function newTour(): TourForm {
    return {
        name: '',
        steps: [],
    }
}

function tourToForm(tour: ProductTour): TourForm {
    return {
        id: tour.id,
        name: tour.name,
        steps: (tour.content?.steps ?? []).map((step) => ({
            id: uuid(),
            selector: step.selector,
            content: step.content,
        })),
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
        confirmStep: (content: JSONContent | null, selector?: string) => ({ content, selector }),
        cancelStep: true,
        selectTour: (id: string | null) => ({ id }),
        newTour: true,
        addStep: true,
        removeStep: (index: number) => ({ index }),
        setHoverElement: (element: HTMLElement | null) => ({ element }),
        updateRects: true,
        saveTour: true,
        deleteTour: (id: string) => ({ id }),
    }),

    loaders(() => ({
        tours: [
            [] as ProductTour[],
            {
                loadTours: async () => {
                    const response = await toolbarFetch('/api/projects/@current/product_tours/')
                    if (!response.ok) {
                        return []
                    }
                    const data = await response.json()
                    return data.results ?? data
                },
            },
        ],
    })),

    reducers({
        buttonProductToursVisible: [
            false,
            {
                showButtonProductTours: () => true,
                hideButtonProductTours: () => false,
            },
        ],
        selectedTourId: [
            null as string | 'new' | null,
            {
                selectTour: (_, { id }) => id,
                newTour: () => 'new',
                saveTourSuccess: (_, { tours }) => tours[0]?.id ?? null,
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
        // Tracks whether user has completed the initial tour setup modal
        tourSetupCompleted: [
            false,
            {
                inspectForElementWithIndex: () => true,
                selectTour: () => false,
                newTour: () => false,
            },
        ],
    }),

    forms(({ actions }) => ({
        tourForm: {
            defaults: { name: '', steps: [] } as TourForm,
            errors: ({ name }) => ({
                name: !name || !name.length ? 'Must name this tour' : undefined,
            }),
            submit: async (formValues) => {
                const { id, name, steps } = formValues
                // Strip element references from steps before saving
                const stepsForApi = steps.map(({ selector, content }) => ({ selector, content }))
                const payload = {
                    name,
                    content: { steps: stepsForApi },
                }

                const url = id ? `/api/projects/@current/product_tours/${id}/` : '/api/projects/@current/product_tours/'
                const method = id ? 'PATCH' : 'POST'

                const response = await toolbarFetch(url, method, payload)

                if (!response.ok) {
                    const error = await response.json()
                    lemonToast.error(error.detail || 'Failed to save tour')
                    throw new Error(error.detail || 'Failed to save tour')
                }

                const savedTour = await response.json()
                lemonToast.success(id ? 'Tour updated' : 'Tour created', {
                    button: {
                        label: 'Open in PostHog',
                        action: () => {
                            // TODO: Add URL when product tours UI is available
                        },
                    },
                })
                actions.loadTours()
                // Close the editing bar after successful save
                actions.selectTour(null)
                return savedTour
            },
        },
    })),

    connect(() => ({
        values: [toolbarConfigLogic, ['dataAttributes']],
    })),

    selectors({
        selectedTour: [
            (s) => [s.selectedTourId, s.tours],
            (selectedTourId, tours): TourForm | null => {
                if (selectedTourId === 'new') {
                    return newTour()
                }
                if (selectedTourId) {
                    const tour = tours.find((t) => t.id === selectedTourId)
                    if (tour) {
                        return tourToForm(tour)
                    }
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
                if (selectedTour.id) {
                    actions.setTourFormValue('id', selectedTour.id)
                }
                actions.setTourFormValue('name', selectedTour.name)
                actions.setTourFormValue('steps', selectedTour.steps)
            }
        },
    })),

    listeners(({ actions, values }) => ({
        confirmStep: ({ content, selector: selectorOverride }) => {
            if (values.tourForm && values.selectedElement) {
                const actionStep = elementToActionStep(values.selectedElement, values.dataAttributes)
                const selector = selectorOverride ?? actionStep.selector ?? ''

                const steps = [...(values.tourForm.steps || [])]
                const index = values.inspectingElement

                // When editing an existing step, preserve its ID; otherwise generate a new one
                const existingStep = index !== null && index < steps.length ? steps[index] : null
                const stepId = existingStep?.id ?? uuid()

                const newStep: TourStep = {
                    id: stepId,
                    selector,
                    content,
                    element: values.selectedElement,
                }

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
            if (!step) {
                return
            }

            // Try to find the element - first check cached reference, then query by selector
            let element = step.element
            if (!element || !document.body.contains(element)) {
                element = step.selector
                    ? ((document.querySelector(step.selector) as HTMLElement | null) ?? undefined)
                    : undefined
            }

            if (element) {
                actions.selectElement(element)
            }
            // If element not found, reducer already set inspectingElement
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
        selectTour: ({ id }) => {
            if (id !== null) {
                // Close the sidebar menu when selecting a tour to edit
                toolbarLogic.actions.setVisibleMenu('none')
            }
        },
        saveTour: () => {
            actions.submitTourForm()
        },
        deleteTour: async ({ id }) => {
            const response = await toolbarFetch(`/api/projects/@current/product_tours/${id}/`, 'DELETE')
            if (response.ok) {
                lemonToast.success('Tour deleted')
                actions.loadTours()
                actions.selectTour(null)
            } else {
                lemonToast.error('Failed to delete tour')
            }
        },
        showButtonProductTours: () => {
            toolbarPosthogJS.capture('toolbar mode triggered', { mode: 'product-tours', enabled: true })
            actions.loadTours()
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
