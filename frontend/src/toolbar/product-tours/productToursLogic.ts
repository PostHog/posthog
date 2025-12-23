import { JSONContent } from '@tiptap/core'
import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { uuid } from 'lib/utils'
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
    ProductTourSurveyQuestion,
    StepOrderVersion,
} from '~/types'

import type { productToursLogicType } from './productToursLogicType'
import { captureScreenshot, getElementMetadata, getSmartUrlDefaults } from './utils'

const RECENT_GOALS_KEY = 'posthog-product-tours-recent-goals'

export type AIGenerationStep = 'idle' | 'capturing' | 'analyzing' | 'generating' | 'done' | 'error'

/**
 * Editor state machine - explicit states instead of multiple boolean flags.
 *
 * - idle: Default state, no hover effects, step badges visible. Cmd/ctrl+click passes through.
 * - selecting: User is picking an element from the page. Hover highlighting active.
 * - editing: User is editing a step's content. Editor panel is open.
 */
export type EditorState =
    | { mode: 'idle' }
    | { mode: 'selecting'; stepIndex: number }
    | { mode: 'editing'; stepIndex: number; stepType: ProductTourStepType }

function saveRecentGoal(goal: string): void {
    try {
        const stored = localStorage.getItem(RECENT_GOALS_KEY)
        const goals: string[] = stored ? JSON.parse(stored) : []
        const filtered = goals.filter((g) => g !== goal)
        filtered.unshift(goal)
        localStorage.setItem(RECENT_GOALS_KEY, JSON.stringify(filtered.slice(0, 5)))
    } catch {
        // Ignore localStorage errors
    }
}

export interface TourStep extends ProductTourStep {
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
    return step.selector ? (document.querySelector(step.selector) as HTMLElement | null) : null
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
        editStep: (index: number) => ({ index }),
        changeStepElement: true,
        selectElement: (element: HTMLElement) => ({ element }),
        setHoverElement: (element: HTMLElement | null) => ({ element }),
        clearSelectedElement: true,
        confirmStep: (
            content: JSONContent | null,
            selector?: string,
            survey?: ProductTourSurveyQuestion,
            progressionTrigger?: ProductTourProgressionTriggerType
        ) => ({ content, selector, survey, progressionTrigger }),
        cancelEditing: true,
        removeStep: (index: number) => ({ index }),

        // Tour CRUD
        selectTour: (id: string | null) => ({ id }),
        newTour: true,
        saveTour: true,
        previewTour: true,
        stopPreview: true,
        deleteTour: (id: string) => ({ id }),

        updateRects: true,

        // Goal modal
        openGoalModal: true,
        closeGoalModal: true,
        startFromGoalModal: true,

        // AI generation
        setAIGoal: (goal: string) => ({ goal }),
        generateWithAI: true,
        generateWithAISuccess: (steps: Array<{ selector?: string; content: JSONContent }>, name?: string) => ({
            steps,
            name,
        }),
        generateWithAIFailure: (error: string) => ({ error }),
        setAIGenerationStep: (step: AIGenerationStep) => ({ step }),

        // Creation
        startCreation: true,
        setCachedScreenshot: (screenshot: string | null) => ({ screenshot }),
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
                previewTour: () => true,
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
                setEditorState: (state, { state: newState }) => (newState.mode === 'editing' ? state : null),
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
        goalModalOpen: [
            false,
            {
                openGoalModal: () => true,
                closeGoalModal: () => false,
                startFromGoalModal: () => false,
            },
        ],
        aiGoal: [
            '',
            {
                setAIGoal: (_, { goal }) => goal,
                selectTour: () => '',
            },
        ],
        aiGenerating: [
            false,
            {
                generateWithAI: () => true,
                generateWithAISuccess: () => false,
                generateWithAIFailure: () => false,
            },
        ],
        aiGenerationStep: [
            'idle' as AIGenerationStep,
            {
                generateWithAI: () => 'capturing' as AIGenerationStep,
                setAIGenerationStep: (_, { step }) => step,
                generateWithAISuccess: () => 'done' as AIGenerationStep,
                generateWithAIFailure: () => 'error' as AIGenerationStep,
                selectTour: () => 'idle' as AIGenerationStep,
            },
        ],
        aiError: [
            null as string | null,
            {
                generateWithAI: () => null,
                generateWithAIFailure: (_, { error }) => error,
                selectTour: () => null,
            },
        ],
        cachedScreenshot: [
            null as string | null,
            {
                setCachedScreenshot: (_, { screenshot }) => screenshot,
                selectTour: () => null,
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

                // Strip element references from steps before saving (element is a local-only DOM ref)
                const stepsForApi = steps.map(({ element: _, ...step }) => step)

                // Get existing step_order_history if updating an existing tour
                const existingTour = id ? values.tours.find((t: ProductTour) => t.id === id) : null
                const existingHistory = existingTour?.content?.step_order_history

                // Update history if step order changed (or create initial version for new tours)
                const stepOrderHistory = getUpdatedStepOrderHistory(stepsForApi, existingHistory)

                // For new tours, set smart URL defaults based on current page
                const urlDefaults = !isUpdate ? getSmartUrlDefaults() : null

                const payload = {
                    name,
                    content: {
                        // Preserve existing content fields (appearance, conditions) when updating
                        ...existingTour?.content,
                        steps: stepsForApi,
                        step_order_history: stepOrderHistory,
                        // Set smart URL defaults for new tours (don't override existing conditions)
                        ...(!isUpdate && !existingTour?.content?.conditions
                            ? {
                                  conditions: {
                                      url: urlDefaults?.url,
                                      urlMatchType: urlDefaults?.urlMatchType,
                                  },
                              }
                            : {}),
                    },
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
                const { apiURL } = values

                lemonToast.success(isUpdate ? 'Tour updated' : 'Tour created', {
                    button: {
                        label: 'Open in PostHog',
                        action: () => window.open(`${apiURL}${urls.productTour(savedTour.id)}`, '_blank'),
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
        values: [toolbarConfigLogic, ['dataAttributes', 'apiURL', 'userIntent', 'productTourId', 'posthog']],
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
        isEditing: [(s) => [s.editorState], (editorState) => editorState.mode === 'editing'],
        editingStepIndex: [
            (s) => [s.editorState],
            (editorState): number | null =>
                editorState.mode === 'editing' || editorState.mode === 'selecting' ? editorState.stepIndex : null,
        ],
        editingStepType: [
            (s) => [s.editorState],
            (editorState): ProductTourStepType | null => (editorState.mode === 'editing' ? editorState.stepType : null),
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
        editingStep: [
            (s) => [s.editingStepIndex, s.tourForm],
            (editingStepIndex, tourForm): TourStep | null => {
                if (editingStepIndex === null) {
                    return null
                }
                return tourForm?.steps?.[editingStepIndex] ?? null
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
            if (stepType === 'element') {
                // Element steps need element selection first
                actions.setEditorState({ mode: 'selecting', stepIndex: nextIndex })
            } else {
                // Modal/survey steps go directly to editing
                actions.setEditorState({ mode: 'editing', stepIndex: nextIndex, stepType })
            }
        },
        editStep: ({ index }) => {
            const step = values.tourForm?.steps?.[index]
            if (!step) {
                return
            }

            // For element steps, try to find and highlight the element
            if (step.type === 'element') {
                const element = getStepElement(step)
                if (element) {
                    element.scrollIntoView({ behavior: 'smooth', block: 'center' })
                    actions.selectElement(element)
                } else {
                    // Element not found - clear so editor shows centered with warning
                    actions.clearSelectedElement()
                }
            }

            actions.setEditorState({ mode: 'editing', stepIndex: index, stepType: step.type })
        },
        changeStepElement: () => {
            // Re-enter selecting mode for the current step
            const { editorState } = values
            if (editorState.mode === 'editing') {
                actions.setEditorState({ mode: 'selecting', stepIndex: editorState.stepIndex })
            }
        },
        selectElement: ({ element }) => {
            const { editorState, tourForm, dataAttributes } = values
            if (editorState.mode !== 'selecting') {
                return
            }

            const { stepIndex } = editorState
            const isChangingExistingStep = tourForm && stepIndex < (tourForm.steps?.length ?? 0)

            if (isChangingExistingStep) {
                // Changing element for existing step - update immediately
                const selector = elementToActionStep(element, dataAttributes).selector ?? ''
                const steps = [...(tourForm.steps || [])]
                steps[stepIndex] = {
                    ...steps[stepIndex],
                    selector,
                    element,
                }
                actions.setTourFormValue('steps', steps)
                actions.setEditorState({ mode: 'idle' })
            } else {
                // New step - go to editing mode
                actions.setEditorState({
                    mode: 'editing',
                    stepIndex,
                    stepType: 'element',
                })
            }
        },
        confirmStep: ({ content, selector: selectorOverride, survey, progressionTrigger }) => {
            const { editorState, tourForm, selectedElement } = values
            if (editorState.mode !== 'editing' || !tourForm) {
                return
            }

            const { stepIndex, stepType } = editorState
            const steps = [...(tourForm.steps || [])]
            const existingStep = stepIndex < steps.length ? steps[stepIndex] : null

            // For element steps, use selector from UI (which handles all derivation logic)
            // Preserve existing selector if none provided (e.g., editing content only)
            const selector = stepType === 'element' ? (selectorOverride ?? existingStep?.selector) : undefined

            const newStep: TourStep = {
                id: existingStep?.id ?? uuid(),
                type: stepType,
                selector,
                content,
                element: selectedElement ?? existingStep?.element,
                ...(survey ? { survey } : {}),
                ...(progressionTrigger ? { progressionTrigger } : {}),
            }

            if (stepIndex < steps.length) {
                steps[stepIndex] = newStep
            } else {
                steps.push(newStep)
            }

            actions.setTourFormValue('steps', steps)
            actions.setEditorState({ mode: 'idle' })
        },
        removeStep: ({ index }) => {
            if (values.tourForm) {
                const steps = [...(values.tourForm.steps || [])]
                steps.splice(index, 1)
                actions.setTourFormValue('steps', steps)
                actions.setEditorState({ mode: 'idle' })
            }
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
        previewTour: () => {
            const { tourForm, posthog, selectedTourId, tours } = values
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
                steps: tourForm.steps,
                appearance: existingTour?.content?.appearance,
            }

            productTours.previewTour(tour)
        },
        stopPreview: () => {
            toolbarLogic.actions.toggleMinimized(false)
        },
        updateRects: () => {
            // When editing an element step, check if selected element is still valid
            const { editorState, selectedElement, tourForm } = values
            if (editorState.mode === 'editing' && editorState.stepType === 'element') {
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
        generateWithAI: async () => {
            const steps = values.tourForm?.steps ?? []
            const nonSurveySteps = steps.filter((step) => step.type !== 'survey')

            if (nonSurveySteps.length === 0) {
                lemonToast.error('Add at least one element before generating')
                actions.generateWithAIFailure('No elements selected')
                return
            }

            try {
                actions.setAIGenerationStep('capturing')
                let screenshot = values.cachedScreenshot
                if (!screenshot) {
                    try {
                        screenshot = await captureScreenshot()
                    } catch (e) {
                        console.warn('[AI Generate] Failed to capture screenshot:', e)
                    }
                }

                actions.setAIGenerationStep('analyzing')
                const elements = nonSurveySteps.map((step) => {
                    let metadata = { selector: step.selector, tag: 'unknown', text: '', attributes: {} }
                    if (step.element && document.body.contains(step.element)) {
                        metadata = {
                            ...getElementMetadata(step.element),
                            selector: step.selector,
                        }
                    } else if (step.selector) {
                        const el = document.querySelector(step.selector) as HTMLElement | null
                        if (el) {
                            metadata = {
                                ...getElementMetadata(el),
                                selector: step.selector,
                            }
                        }
                    }
                    return metadata
                })

                actions.setAIGenerationStep('generating')
                const response = await toolbarFetch('/api/projects/@current/product_tours/generate/', 'POST', {
                    screenshot,
                    elements,
                    goal: values.aiGoal,
                })

                if (!response.ok) {
                    const error = await response.json()
                    throw new Error(error.error || 'Failed to generate tour content')
                }

                const data = await response.json()

                if (values.aiGoal.trim()) {
                    saveRecentGoal(values.aiGoal.trim())
                }

                actions.generateWithAISuccess(data.steps, data.name)
            } catch (e) {
                const message = e instanceof Error ? e.message : 'Failed to generate tour content'
                lemonToast.error(message)
                actions.generateWithAIFailure(message)
            }
        },
        generateWithAISuccess: ({ steps: generatedSteps, name }) => {
            if (name) {
                actions.setTourFormValue('name', name)
            }

            const currentSteps = [...(values.tourForm?.steps ?? [])]
            let aiStepIndex = 0
            currentSteps.forEach((step, i) => {
                if (step.type === 'survey') {
                    return
                }
                if (aiStepIndex < generatedSteps.length) {
                    const aiStep = generatedSteps[aiStepIndex]
                    currentSteps[i] = { ...currentSteps[i], content: aiStep.content }
                    aiStepIndex++
                }
            })

            actions.setTourFormValue('steps', currentSteps)
            lemonToast.success('Tour content generated!')
        },
        startCreation: () => {
            toolbarLogic.actions.setVisibleMenu('none')
            actions.openGoalModal()
        },
        startFromGoalModal: async () => {
            actions.newTour()
            if (values.aiGoal.trim()) {
                actions.setTourFormValue('name', values.aiGoal.trim())
            }

            try {
                const screenshot = await captureScreenshot().catch(() => null)
                actions.setCachedScreenshot(screenshot)
            } catch (e) {
                console.warn('[Creation] Failed to capture screenshot:', e)
            }
        },
        loadToursSuccess: () => {
            const { userIntent, productTourId } = values
            if (userIntent === 'edit-product-tour' && productTourId) {
                actions.selectTour(productTourId)
                toolbarConfigLogic.actions.clearUserIntent()
            } else if (userIntent === 'add-product-tour') {
                actions.startCreation()
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
                // Cmd/ctrl+click always passes through (for click-through navigation)
                if (e.metaKey || e.ctrlKey) {
                    return
                }

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
                            actions.editStep(i)
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
