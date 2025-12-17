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
import { ProductTour, ProductTourStep, ProductTourSurveyQuestion, StepOrderVersion } from '~/types'

import type { productToursLogicType } from './productToursLogicType'
import { captureScreenshot, getElementMetadata, getSmartUrlDefaults } from './utils'

const RECENT_GOALS_KEY = 'posthog-product-tours-recent-goals'

export type AIGenerationStep = 'idle' | 'capturing' | 'analyzing' | 'generating' | 'done' | 'error'

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

export interface TourStep {
    id: string
    selector: string
    content: JSONContent | null
    /** Local-only: reference to DOM element, not persisted */
    element?: HTMLElement
    /** Inline survey question config - if present, this is a survey step */
    survey?: ProductTourSurveyQuestion
    /** ID of the auto-created survey for this step (set by backend, must be preserved on updates) */
    linkedSurveyId?: string
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
            id: step.id || uuid(), // Preserve existing ID, generate new one only if missing
            selector: step.selector,
            content: step.content,
            survey: step.survey,
            linkedSurveyId: step.linkedSurveyId,
        })),
    }
}

function isToolbarElement(element: HTMLElement): boolean {
    const toolbar = document.getElementById(TOOLBAR_ID)
    return toolbar?.contains(element) ?? false
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
        inspectForElementWithIndex: (index: number | null) => ({ index }),
        setInspectingElementIndex: (index: number | null) => ({ index }),
        editStep: (index: number) => ({ index }),
        selectElement: (element: HTMLElement) => ({ element }),
        confirmStep: (content: JSONContent | null, selector?: string, survey?: ProductTourSurveyQuestion) => ({
            content,
            selector,
            survey,
        }),
        cancelStep: true,
        selectTour: (id: string | null) => ({ id }),
        newTour: true,
        addStep: true,
        addModalStep: true,
        addSurveyStep: true,
        setEditingModalStep: (isModal: boolean) => ({ isModal }),
        setEditingSurveyStep: (isSurvey: boolean) => ({ isSurvey }),
        removeStep: (index: number) => ({ index }),
        setHoverElement: (element: HTMLElement | null) => ({ element }),
        updateRects: true,
        saveTour: true,
        deleteTour: (id: string) => ({ id }),
        // Goal modal actions
        openGoalModal: true,
        closeGoalModal: true,
        startSelectionMode: true,
        // AI generation actions
        setAIGoal: (goal: string) => ({ goal }),
        generateWithAI: true,
        generateWithAISuccess: (steps: Array<{ selector: string; content: JSONContent }>, name?: string) => ({
            steps,
            name,
        }),
        generateWithAIFailure: (error: string) => ({ error }),
        setAIGenerationStep: (step: AIGenerationStep) => ({ step }),
        // Creation mode actions
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
                setInspectingElementIndex: (_, { index }) => index,
                editStep: (_, { index }) => index,
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
                addModalStep: () => null,
                addSurveyStep: () => null,
                setEditingModalStep: (state, { isModal }) => (isModal ? null : state),
                setEditingSurveyStep: (state, { isSurvey }) => (isSurvey ? null : state),
                hideButtonProductTours: () => null,
                // Note: confirmStep clears this AFTER the listener runs via actions.cancelStep()
            },
        ],
        editingModalStep: [
            false,
            {
                addModalStep: () => true,
                setEditingModalStep: (_, { isModal }) => isModal,
                selectElement: () => false,
                cancelStep: () => false,
                confirmStep: () => false,
                inspectForElementWithIndex: () => false,
                selectTour: () => false,
                hideButtonProductTours: () => false,
                addSurveyStep: () => false, // Survey steps use their own flag
            },
        ],
        editingSurveyStep: [
            false,
            {
                addSurveyStep: () => true,
                setEditingSurveyStep: (_, { isSurvey }) => isSurvey,
                selectElement: () => false,
                cancelStep: () => false,
                confirmStep: () => false,
                inspectForElementWithIndex: () => false,
                selectTour: () => false,
                hideButtonProductTours: () => false,
                addModalStep: () => false, // Modal steps use their own flag
            },
        ],
        rectUpdateCounter: [
            0,
            {
                updateRects: (state) => state + 1,
            },
        ],
        // Goal modal state
        goalModalOpen: [
            false,
            {
                openGoalModal: () => true,
                closeGoalModal: () => false,
                startSelectionMode: () => false,
            },
        ],
        // AI generation state
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
        values: [toolbarConfigLogic, ['dataAttributes', 'apiURL']],
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
        isEditingStep: [
            (s) => [s.selectedElement, s.editingModalStep, s.editingSurveyStep],
            (selectedElement, editingModalStep, editingSurveyStep) =>
                selectedElement !== null || editingModalStep || editingSurveyStep,
        ],
        editingStep: [
            (s) => [s.inspectingElement, s.tourForm],
            (inspectingElement, tourForm): TourStep | null => {
                if (inspectingElement === null) {
                    return null
                }
                return tourForm?.steps?.[inspectingElement] ?? null
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
        confirmStep: ({ content, selector: selectorOverride, survey }) => {
            // Check inspectingElement since editingModalStep reducer runs before listener
            if (values.tourForm && values.inspectingElement !== null) {
                // For modal/survey steps (no element), selector is empty by default
                const selector = values.selectedElement
                    ? (selectorOverride ??
                      elementToActionStep(values.selectedElement, values.dataAttributes).selector ??
                      '')
                    : (selectorOverride ?? '')

                const steps = [...(values.tourForm.steps || [])]
                const index = values.inspectingElement

                // When editing an existing step, preserve its ID; otherwise generate a new one
                const existingStep = index !== null && index < steps.length ? steps[index] : null
                const stepId = existingStep?.id ?? uuid()

                const newStep: TourStep = {
                    id: stepId,
                    selector,
                    content,
                    element: values.selectedElement ?? undefined,
                    ...(survey ? { survey } : {}),
                }

                if (index !== null && index < steps.length) {
                    steps[index] = newStep
                } else {
                    steps.push(newStep)
                }

                actions.setTourFormValue('steps', steps)
                // Clear editing state and go to selecting next element
                actions.cancelStep()
                actions.inspectForElementWithIndex(steps.length)
            }
        },
        editStep: ({ index }) => {
            const step = values.tourForm?.steps?.[index]
            if (!step) {
                return
            }

            // Survey steps are always modal-style
            if (step.survey) {
                actions.setEditingSurveyStep(true)
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
                // Scroll element into view so the card is visible
                element.scrollIntoView({ behavior: 'smooth', block: 'center' })
                actions.selectElement(element)
            } else {
                // Modal step (no selector/element) - edit in centered modal mode
                actions.setEditingModalStep(true)
            }
        },
        selectElement: ({ element }) => {
            // Auto-detect if this element belongs to an existing step
            const steps = values.tourForm?.steps ?? []
            const matchingIndex = steps.findIndex(
                (step) => step.element === element || (step.selector && element.matches(step.selector))
            )
            if (matchingIndex >= 0) {
                // Use setInspectingElementIndex to avoid clearing selectedElement
                actions.setInspectingElementIndex(matchingIndex)
            }
        },
        addStep: () => {
            const nextIndex = values.tourForm?.steps?.length ?? 0
            actions.inspectForElementWithIndex(nextIndex)
        },
        addModalStep: () => {
            const nextIndex = values.tourForm?.steps?.length ?? 0
            actions.setInspectingElementIndex(nextIndex)
        },
        addSurveyStep: () => {
            const nextIndex = values.tourForm?.steps?.length ?? 0
            actions.setInspectingElementIndex(nextIndex)
            // editingSurveyStep reducer handles setting the flag
        },
        removeStep: ({ index }) => {
            if (values.tourForm) {
                const steps = [...(values.tourForm.steps || [])]
                steps.splice(index, 1)
                actions.setTourFormValue('steps', steps)
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
            // Filter out survey steps - AI should only generate content for element/modal steps
            const nonSurveySteps = steps.filter((step) => !step.survey)

            if (nonSurveySteps.length === 0) {
                lemonToast.error('Add at least one element before generating')
                actions.generateWithAIFailure('No elements selected')
                return
            }

            try {
                // Step 1: Use cached screenshot or capture new one
                actions.setAIGenerationStep('capturing')
                let screenshot = values.cachedScreenshot
                if (!screenshot) {
                    try {
                        screenshot = await captureScreenshot()
                    } catch (e) {
                        console.warn('[AI Generate] Failed to capture screenshot:', e)
                    }
                }

                // Step 2: Build element metadata (only for non-survey steps)
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

                // Step 3: Call AI
                actions.setAIGenerationStep('generating')
                const response = await toolbarFetch('/api/projects/@current/product_tours/generate/', 'POST', {
                    screenshot,
                    elements,
                    goal: values.aiGoal,
                })

                if (!response.ok) {
                    const error = await response.json()
                    console.error('[AI Generate] API error:', error)
                    throw new Error(error.error || 'Failed to generate tour content')
                }

                const data = await response.json()

                // Save goal to recent goals
                if (values.aiGoal.trim()) {
                    saveRecentGoal(values.aiGoal.trim())
                }

                actions.generateWithAISuccess(data.steps, data.name)
            } catch (e) {
                console.error('[AI Generate] Error:', e)
                const message = e instanceof Error ? e.message : 'Failed to generate tour content'
                lemonToast.error(message)
                actions.generateWithAIFailure(message)
            }
        },
        generateWithAISuccess: ({ steps: generatedSteps, name }) => {
            // Set name if provided
            if (name) {
                actions.setTourFormValue('name', name)
            }

            // Merge AI-generated content into existing steps, skipping survey steps
            const currentSteps = [...(values.tourForm?.steps ?? [])]
            let aiStepIndex = 0
            currentSteps.forEach((step, i) => {
                // Skip survey steps - AI doesn't generate content for them
                if (step.survey) {
                    return
                }
                if (aiStepIndex < generatedSteps.length) {
                    const aiStep = generatedSteps[aiStepIndex] as { selector: string; content: JSONContent }
                    currentSteps[i] = {
                        ...currentSteps[i],
                        content: aiStep.content,
                    }
                    aiStepIndex++
                }
            })

            actions.setTourFormValue('steps', currentSteps)
            lemonToast.success('Tour content generated!')
        },
        // Opens the goal modal
        startCreation: () => {
            toolbarLogic.actions.setVisibleMenu('none')
            actions.openGoalModal()
        },
        // After setting goal, start creating a new tour
        startSelectionMode: async () => {
            actions.newTour()
            // Default tour name to the goal
            if (values.aiGoal.trim()) {
                actions.setTourFormValue('name', values.aiGoal.trim())
            }
            actions.inspectForElementWithIndex(0)

            // Capture screenshot in background for later AI generation
            try {
                const screenshot = await captureScreenshot().catch(() => null)
                actions.setCachedScreenshot(screenshot)
            } catch (e) {
                console.warn('[Creation] Failed to capture screenshot:', e)
            }
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
