import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import { findElement } from 'posthog-js/dist/element-inference'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { uuid } from 'lib/utils'
import { ProductTourEvent } from 'scenes/product-tours/constants'
import { prepareStepForRender, prepareStepsForRender } from 'scenes/product-tours/editor/generateStepHtml'
import { createDefaultStep, getDefaultStepContent } from 'scenes/product-tours/stepUtils'
import { urls } from 'scenes/urls'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { ElementRect } from '~/toolbar/types'
import { TOOLBAR_ID, elementToActionStep, getRectForElement } from '~/toolbar/utils'
import {
    ProductTour,
    ProductTourProgressionTriggerType,
    ProductTourStep,
    ProductTourStepType,
    StepOrderVersion,
} from '~/types'

import { inferSelector } from './elementInference'
import type { productToursLogicType } from './productToursLogicType'
import { PRODUCT_TOURS_SIDEBAR_TRANSITION_MS, captureAndUploadElementScreenshot } from './utils'

/**
 * Editor state machine - explicit states instead of multiple boolean flags.
 *
 * - idle: Default state, no hover effects, step badges visible. Cmd/ctrl+click passes through.
 * - selecting: User is picking an element from the page. Hover highlighting active.
 */
export type EditorState = { mode: 'idle' } | { mode: 'selecting'; stepIndex: number }

export interface TourStep extends ProductTourStep {
    /** Local-only: reference to DOM element, not persisted */
    element?: HTMLElement
}

export interface TourForm {
    id?: string
    name: string
    steps: TourStep[]
}

export const PRODUCT_TOURS_MIN_JS_VERSION = '1.324.0'

export function hasMinProductToursVersion(version: string): boolean {
    const [major, minor] = version.split('.').map(Number)
    return major > 1 || (major === 1 && minor >= 324)
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
            ...step,
            id: step.id || uuid(),
        })),
    }
}

function isToolbarElement(element: HTMLElement): boolean {
    const toolbar = document.getElementById(TOOLBAR_ID)
    return toolbar?.contains(element) ?? false
}

/** Get the DOM element for a step, checking cached ref is still valid */
export function getStepElement(step: TourStep): HTMLElement | null {
    if (step.element && document.body.contains(step.element)) {
        return step.element
    }

    const useManualSelector = step.useManualSelector ?? false

    if (useManualSelector) {
        if (!step.selector) {
            return null
        }
        return document.querySelector(step.selector) as HTMLElement | null
    }

    if (!step.inferenceData) {
        return step.selector ? (document.querySelector(step.selector) as HTMLElement | null) : null
    }

    return findElement(step.inferenceData)
}

/** Check if steps have changed compared to the latest version in history */
function hasStepsChanged(currentSteps: ProductTourStep[], history: StepOrderVersion[] | undefined): boolean {
    if (!history || history.length === 0) {
        return true // No history means we need to create the first version
    }
    const latestVersion = history[history.length - 1]
    if (currentSteps.length !== latestVersion.steps.length) {
        return true
    }
    return currentSteps.some((step, index) => step.id !== latestVersion.steps[index].id)
}

/** Create updated step order history, appending a new version if steps changed */
function getUpdatedStepOrderHistory(
    currentSteps: ProductTourStep[],
    existingHistory: StepOrderVersion[] | undefined
): StepOrderVersion[] {
    const history = existingHistory ? [...existingHistory] : []

    if (hasStepsChanged(currentSteps, history)) {
        history.push({
            id: uuid(),
            steps: currentSteps,
            created_at: new Date().toISOString(),
        })
    }

    return history
}

export const productToursLogic = kea<productToursLogicType>([
    path(['toolbar', 'product-tours', 'productToursLogic']),

    actions({
        showButtonProductTours: true,
        hideButtonProductTours: true,

        setEditorState: (state: EditorState) => ({ state }),

        // Step actions
        addStep: (stepType: ProductTourStepType) => ({ stepType }),
        selectElement: (element: HTMLElement) => ({ element }),
        setHoverElement: (element: HTMLElement | null) => ({ element }),
        clearSelectedElement: true,
        cancelEditing: true,
        removeStep: (index: number) => ({ index }),

        // Step configuration
        setStepTargetingMode: (index: number, useManual: boolean) => ({ index, useManual }),
        updateStepSelector: (index: number, selector: string) => ({ index, selector }),
        updateStepProgressionTrigger: (index: number, trigger: ProductTourProgressionTriggerType) => ({
            index,
            trigger,
        }),

        // Tour CRUD
        selectTour: (id: string | null) => ({ id }),
        newTour: true,
        saveTour: true,
        saveAndEditInPostHog: true,
        deleteTour: (id: string) => ({ id }),

        // Preview
        previewTour: true,
        startPreviewMode: true,
        stopPreview: true,
        setLaunchedFromMainApp: (value: boolean) => ({ value }),

        updateRects: true,

        // Expanded step tracking
        setExpandedStepIndex: (index: number | null) => ({ index }),

        // Sidebar transition state (hide highlights during animation)
        setSidebarTransitioning: (transitioning: boolean) => ({ transitioning }),
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
        isPreviewing: [
            false,
            {
                startPreviewMode: () => true,
                stopPreview: () => false,
                selectTour: () => false,
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
        editorState: [
            { mode: 'idle' } as EditorState,
            {
                setEditorState: (_, { state }) => state,
                selectTour: () => ({ mode: 'idle' }),
                newTour: () => ({ mode: 'idle' }),
                hideButtonProductTours: () => ({ mode: 'idle' }),
                cancelEditing: () => ({ mode: 'idle' }),
            },
        ],
        // Element currently being hovered during selection mode
        hoverElement: [
            null as HTMLElement | null,
            {
                setHoverElement: (_, { element }) => element,
                setEditorState: () => null,
                hideButtonProductTours: () => null,
            },
        ],
        // Element selected for the current step being edited
        selectedElement: [
            null as HTMLElement | null,
            {
                selectElement: (_, { element }) => element,
                clearSelectedElement: () => null,
                setEditorState: () => null,
                cancelEditing: () => null,
                hideButtonProductTours: () => null,
            },
        ],
        rectUpdateCounter: [
            0,
            {
                updateRects: (state) => state + 1,
            },
        ],
        expandedStepIndex: [
            null as number | null,
            {
                setExpandedStepIndex: (_, { index }) => index,
                selectTour: () => null,
                newTour: () => null,
                removeStep: () => null,
            },
        ],
        sidebarTransitioning: [
            false,
            {
                setSidebarTransitioning: (_, { transitioning }) => transitioning,
                selectTour: () => true,
            },
        ],
        pendingEditInPostHog: [
            false,
            {
                saveAndEditInPostHog: () => true,
                selectTour: () => false,
                submitTourFormFailure: () => false,
            },
        ],
        launchedFromMainApp: [
            false,
            {
                setLaunchedFromMainApp: (_, { value }) => value,
                selectTour: (state, { id }) => (id === null ? false : state),
            },
        ],
    }),

    forms(({ values, actions }) => ({
        tourForm: {
            defaults: { name: '', steps: [] } as TourForm,
            errors: ({ name, id }) => {
                if (!name || !name.length) {
                    return { name: 'Must name this tour' }
                }
                // Check for duplicate names (excluding the current tour being edited)
                const isDuplicate = values.tours.some(
                    (tour: ProductTour) => tour.name.toLowerCase() === name.toLowerCase() && tour.id !== id
                )
                if (isDuplicate) {
                    return { name: 'A tour with this name already exists' }
                }
                return {}
            },
            submit: async (formValues) => {
                const { id, name, steps } = formValues
                const isUpdate = !!id

                // Strip element references and add pre-computed HTML for SDK consumption
                const stepsForApi = steps.map(({ element: _, ...step }) => prepareStepForRender(step))

                // Get existing step_order_history if updating an existing tour
                const existingTour = id ? values.tours.find((t: ProductTour) => t.id === id) : null
                const existingHistory = existingTour?.content?.step_order_history

                // Update history if step order changed (or create initial version for new tours)
                const stepOrderHistory = getUpdatedStepOrderHistory(stepsForApi, existingHistory)

                const payload = {
                    name,
                    content: {
                        // Preserve existing content fields (appearance, conditions) when updating
                        ...existingTour?.content,
                        steps: stepsForApi,
                        step_order_history: stepOrderHistory,
                    },
                    creation_context: 'toolbar',
                }
                const url = isUpdate
                    ? `/api/projects/@current/product_tours/${id}/`
                    : '/api/projects/@current/product_tours/'
                const method = isUpdate ? 'PATCH' : 'POST'

                const response = await toolbarFetch(url, method, payload)

                if (!response.ok) {
                    const error = await response.json()
                    lemonToast.error(error.detail || 'Failed to save tour')
                    throw new Error(error.detail || 'Failed to save tour')
                }

                const savedTour = await response.json()
                const { uiHost, pendingEditInPostHog, launchedFromMainApp } = values

                if (pendingEditInPostHog) {
                    const editUrl = `${uiHost}${urls.productTour(savedTour.id, 'edit=true&tab=steps')}`
                    if (launchedFromMainApp) {
                        window.location.href = editUrl
                    } else {
                        window.open(editUrl, '_blank')
                    }
                } else {
                    lemonToast.success(isUpdate ? 'Tour updated' : 'Tour created', {
                        button: {
                            label: 'Open in PostHog',
                            action: () => window.open(`${uiHost}${urls.productTour(savedTour.id)}`, '_blank'),
                        },
                    })
                }
                actions.loadTours()
                // Close the editing bar after successful save
                actions.selectTour(null)
                return savedTour
            },
        },
    })),

    connect(() => ({
        values: [toolbarConfigLogic, ['dataAttributes', 'uiHost', 'userIntent', 'productTourId', 'posthog']],
    })),

    selectors({
        selectedTour: [
            (s) => [s.selectedTourId, s.tours],
            (selectedTourId, tours): TourForm | null => {
                if (selectedTourId === 'new') {
                    return newTour()
                }
                if (selectedTourId) {
                    const tour = tours.find((t: ProductTour) => t.id === selectedTourId)
                    if (tour) {
                        return tourToForm(tour)
                    }
                }
                return null
            },
        ],
        isSelecting: [(s) => [s.editorState], (editorState) => editorState.mode === 'selecting'],
        selectingStepIndex: [
            (s) => [s.editorState],
            (editorState): number | null => (editorState.mode === 'selecting' ? editorState.stepIndex : null),
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
        stepCount: [(s) => [s.tourForm], (tourForm) => tourForm?.steps?.length ?? 0],
    }),

    subscriptions(({ actions }) => ({
        selectedTour: (selectedTour: TourForm | null) => {
            if (!selectedTour) {
                actions.resetTourForm()
            } else {
                // Always set id (or clear it for new tours)
                actions.setTourFormValue('id', selectedTour.id)
                actions.setTourFormValue('name', selectedTour.name)
                actions.setTourFormValue('steps', selectedTour.steps)
            }
        },
    })),

    listeners(({ actions, values }) => ({
        addStep: ({ stepType }) => {
            const nextIndex = values.tourForm?.steps?.length ?? 0
            toolbarPosthogJS.capture(ProductTourEvent.STEP_ADDED, {
                step_type: stepType,
                step_index: nextIndex,
                tour_id: values.tourForm?.id ?? null,
            })
            if (stepType === 'element') {
                actions.setEditorState({ mode: 'selecting', stepIndex: nextIndex })
            } else {
                const steps = [...(values.tourForm?.steps || [])]
                const newStep = createDefaultStep(stepType) as TourStep
                steps.push(newStep)
                actions.setTourFormValue('steps', steps)
                actions.setExpandedStepIndex(nextIndex)
            }
        },
        selectElement: async ({ element }) => {
            const { editorState, tourForm, dataAttributes } = values
            if (editorState.mode !== 'selecting') {
                return
            }

            const { stepIndex } = editorState
            const selector = elementToActionStep(element, dataAttributes).selector ?? ''
            const inferenceData = inferSelector(element)?.selector
            const screenshot = await captureAndUploadElementScreenshot(element).catch((e) => {
                console.warn('[Product Tours] Failed to capture element screenshot:', e)
                return null
            })

            const steps = [...(tourForm?.steps || [])]
            const existingStep = stepIndex < steps.length ? steps[stepIndex] : null

            const newStep: TourStep = {
                id: existingStep?.id ?? uuid(),
                type: 'element',
                selector,
                content: existingStep?.content ?? getDefaultStepContent(),
                element,
                inferenceData,
                useManualSelector: false,
                progressionTrigger: existingStep?.progressionTrigger ?? 'button',
                ...(screenshot ? { screenshotMediaId: screenshot.mediaId } : {}),
            }

            if (stepIndex < steps.length) {
                steps[stepIndex] = newStep
            } else {
                steps.push(newStep)
            }

            actions.setTourFormValue('steps', steps)
            actions.setEditorState({ mode: 'idle' })
            actions.setExpandedStepIndex(stepIndex)
        },
        removeStep: ({ index }) => {
            if (values.tourForm) {
                const removedStep = values.tourForm.steps?.[index]
                toolbarPosthogJS.capture(ProductTourEvent.STEP_REMOVED, {
                    step_type: removedStep?.type ?? null,
                    step_index: index,
                    tour_id: values.tourForm.id ?? null,
                    remaining_steps: (values.tourForm.steps?.length ?? 1) - 1,
                })
                const steps = [...(values.tourForm.steps || [])]
                steps.splice(index, 1)
                actions.setTourFormValue('steps', steps)
                actions.setEditorState({ mode: 'idle' })
            }
        },
        setStepTargetingMode: ({ index, useManual }) => {
            if (!values.tourForm) {
                return
            }
            const steps = [...(values.tourForm.steps || [])]
            const step = steps[index]
            if (!step || step.type !== 'element') {
                return
            }

            if (useManual) {
                // switching from auto -> manual, wipe inference data and screenshot.
                // this prevents stale data down the line
                steps[index] = {
                    ...step,
                    useManualSelector: true,
                    inferenceData: undefined,
                    screenshotMediaId: undefined,
                }
            } else {
                // switching from manual -> auto: wipe selector data, prompt for re-selection
                steps[index] = {
                    ...step,
                    useManualSelector: false,
                    selector: undefined,
                    inferenceData: undefined,
                    screenshotMediaId: undefined,
                }
                actions.setEditorState({ mode: 'selecting', stepIndex: index })
            }
            actions.setTourFormValue('steps', steps)
        },
        updateStepSelector: ({ index, selector }) => {
            if (!values.tourForm) {
                return
            }
            const steps = [...(values.tourForm.steps || [])]
            const step = steps[index]
            if (!step || step.type !== 'element') {
                return
            }
            steps[index] = { ...step, selector }
            actions.setTourFormValue('steps', steps)
        },
        updateStepProgressionTrigger: ({ index, trigger }) => {
            if (!values.tourForm) {
                return
            }
            const steps = [...(values.tourForm.steps || [])]
            const step = steps[index]
            if (!step) {
                return
            }
            steps[index] = { ...step, progressionTrigger: trigger }
            actions.setTourFormValue('steps', steps)
        },
        newTour: () => {
            toolbarLogic.actions.setVisibleMenu('none')
        },
        selectTour: ({ id }) => {
            if (id !== null) {
                toolbarLogic.actions.setVisibleMenu('none')
            }
        },
        saveTour: () => {
            actions.submitTourForm()
        },
        saveAndEditInPostHog: () => {
            actions.submitTourForm()
        },
        previewTour: () => {
            const { tourForm, posthog, selectedTourId, tours } = values
            if (posthog?.version && !hasMinProductToursVersion(posthog.version)) {
                lemonToast.error(`Requires posthog-js ${PRODUCT_TOURS_MIN_JS_VERSION}+`)
                return
            }

            if (!tourForm || !posthog?.productTours) {
                lemonToast.error('Unable to preview tour')
                return
            }

            // we can clean this up when posthog-js is updated in the main repo...
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const productTours = posthog.productTours as any
            if (typeof productTours.previewTour !== 'function') {
                lemonToast.error('Preview requires an updated version of posthog-js')
                return
            }

            // Check if the first element step's target exists on this page
            const firstElementStep = tourForm.steps.find((step) => step.type === 'element' && step.selector)
            if (firstElementStep && !getStepElement(firstElementStep)) {
                // eslint-disable-next-line no-alert
                alert(
                    "Can't preview tour: the first step targets an element not found on this page.\n\nNavigate to a page where this element exists, or update the selector."
                )
                return
            }

            // Validation passed - now enter preview mode
            toolbarPosthogJS.capture(ProductTourEvent.PREVIEW_STARTED, {
                tour_id: tourForm.id ?? null,
                step_count: tourForm.steps.length,
            })
            actions.startPreviewMode()
            toolbarLogic.actions.toggleMinimized(true)

            // Get appearance from the saved tour if editing an existing one
            const existingTour =
                selectedTourId && selectedTourId !== 'new'
                    ? tours.find((t: ProductTour) => t.id === selectedTourId)
                    : null

            const tour = {
                id: `preview-${Date.now()}`,
                name: tourForm.name || 'Preview Tour',
                type: 'product_tour' as const,
                start_date: null,
                end_date: null,
                steps: prepareStepsForRender(tourForm.steps),
                appearance: existingTour?.content?.appearance,
            }

            // wait for sidebar animation - gross, sorry :(
            setTimeout(() => {
                productTours.previewTour(tour)
            }, PRODUCT_TOURS_SIDEBAR_TRANSITION_MS + 50)
        },
        stopPreview: () => {
            const { selectedTourId, tours, launchedFromMainApp } = values
            const selectedTour = tours.find((t: ProductTour) => t.id === selectedTourId)
            const isAnnouncement = selectedTour?.content?.type === 'announcement'

            if (isAnnouncement) {
                if (launchedFromMainApp) {
                    window.close() // go back to posthog app
                    return
                }
                actions.selectTour(null)
            }
            toolbarLogic.actions.toggleMinimized(false)
        },
        updateRects: () => {
            // if in selecting mode: try to find + highlight element
            const { editorState, selectedElement, tourForm } = values
            if (editorState.mode === 'selecting') {
                const selectedElementValid = selectedElement && document.body.contains(selectedElement)

                if (!selectedElementValid) {
                    // Element missing or detached - try to find it via selector
                    const step = tourForm?.steps?.[editorState.stepIndex]
                    if (step?.selector) {
                        const element = document.querySelector(step.selector) as HTMLElement | null
                        if (element) {
                            actions.selectElement(element)
                        } else if (selectedElement) {
                            // Had an element but it's gone - clear it
                            actions.clearSelectedElement()
                        }
                    }
                }
            }
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
        loadToursSuccess: () => {
            const { userIntent, productTourId } = values
            if (userIntent === 'edit-product-tour' && productTourId) {
                actions.setLaunchedFromMainApp(true)
                actions.selectTour(productTourId)
                toolbarConfigLogic.actions.clearUserIntent()
            } else if (userIntent === 'add-product-tour') {
                actions.newTour()
                toolbarConfigLogic.actions.clearUserIntent()
            } else if (userIntent === 'preview-product-tour' && productTourId) {
                actions.setLaunchedFromMainApp(true)
                actions.selectTour(productTourId)
                actions.previewTour()
                toolbarConfigLogic.actions.clearUserIntent()
            }
        },
    })),

    events(({ actions, values, cache }) => ({
        afterMount: () => {
            actions.loadTours()

            // Watch for DOM changes to update highlights when elements appear/disappear
            cache.mutationTimeout = null as ReturnType<typeof setTimeout> | null
            cache.mutationObserver = new MutationObserver(() => {
                // Debounce updates to avoid performance issues
                if (cache.mutationTimeout) {
                    clearTimeout(cache.mutationTimeout)
                }
                cache.mutationTimeout = setTimeout(() => {
                    actions.updateRects()
                }, 50)
            })
            cache.mutationObserver.observe(document.body, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['style', 'class', 'hidden'],
            })

            cache.onMouseOver = (e: MouseEvent): void => {
                // During preview, don't track hover
                if (values.isPreviewing) {
                    return
                }
                // Only show hover highlight when in selecting mode
                if (values.editorState.mode !== 'selecting') {
                    return
                }
                const target = e.target as HTMLElement
                if (target && !isToolbarElement(target)) {
                    actions.setHoverElement(target)
                }
            }

            cache.onClick = (e: MouseEvent): void => {
                if (values.isPreviewing) {
                    return
                }

                const target = e.target as HTMLElement
                if (!target || isToolbarElement(target)) {
                    return
                }

                // In selecting mode: capture the element
                if (values.editorState.mode === 'selecting') {
                    e.preventDefault()
                    e.stopPropagation()
                    actions.selectElement(target)
                    return
                }

                // In idle mode: check if clicked element belongs to a step
                if (values.editorState.mode === 'idle' && values.tourForm?.steps) {
                    const steps = values.tourForm.steps
                    for (let i = 0; i < steps.length; i++) {
                        const step = steps[i]
                        if (step.type !== 'element') {
                            continue
                        }
                        const stepElement = getStepElement(step)
                        if (stepElement && (stepElement === target || stepElement.contains(target))) {
                            e.preventDefault()
                            e.stopPropagation()
                            actions.setExpandedStepIndex(i)
                            stepElement.scrollIntoView({ behavior: 'smooth', block: 'center' })
                            return
                        }
                    }
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
                if (e.key === 'Escape' && values.editorState.mode !== 'idle') {
                    actions.setEditorState({ mode: 'idle' })
                }
            }

            document.addEventListener('mouseover', cache.onMouseOver, true)
            document.addEventListener('click', cache.onClick, true)
            document.addEventListener('scroll', cache.onScroll, true)
            window.addEventListener('resize', cache.onResize)
            window.addEventListener('keydown', cache.onKeyDown)

            cache.onTourEnded = (): void => {
                if (values.isPreviewing) {
                    actions.stopPreview()
                }
            }
            window.addEventListener('PHProductTourCompleted', cache.onTourEnded)
            window.addEventListener('PHProductTourDismissed', cache.onTourEnded)
        },
        beforeUnmount: () => {
            if (cache.mutationTimeout) {
                clearTimeout(cache.mutationTimeout)
            }
            if (cache.mutationObserver) {
                cache.mutationObserver.disconnect()
            }
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
            if (cache.onTourEnded) {
                window.removeEventListener('PHProductTourCompleted', cache.onTourEnded)
                window.removeEventListener('PHProductTourDismissed', cache.onTourEnded)
            }
        },
    })),
])
