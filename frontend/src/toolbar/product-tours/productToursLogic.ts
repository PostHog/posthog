import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { findElement, getElementPath } from 'posthog-js/dist/element-inference'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { ProductTourEvent } from 'scenes/product-tours/constants'
import { prepareStepsForRender } from 'scenes/product-tours/editor/generateStepHtml'
import { urls } from 'scenes/urls'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { ElementRect } from '~/toolbar/types'
import { TOOLBAR_ID, elementToActionStep, getRectForElement } from '~/toolbar/utils'
import { ProductTour, ProductTourStep } from '~/types'

import { inferSelector } from './elementInference'
import type { productToursLogicType } from './productToursLogicType'
import { captureAndUploadElementScreenshot, getElementMetadata } from './utils'

/**
 * Simplified editor state - only idle or selecting.
 * Editing is now done in the main PostHog app.
 */
export type EditorState = { mode: 'idle' } | { mode: 'selecting'; stepIndex: number }

export interface TourStep extends ProductTourStep {
    /** Local-only: reference to DOM element, not persisted */
    element?: HTMLElement
}

function isToolbarElement(element: HTMLElement): boolean {
    const toolbar = document.getElementById(TOOLBAR_ID)
    return toolbar?.contains(element) ?? false
}

/** Get the DOM element for a step, checking cached ref is still valid */
export function getStepElement(step: TourStep, options?: { logInference?: boolean }): HTMLElement | null {
    if (step.element && document.body.contains(step.element)) {
        return step.element
    }

    const result = step.selector ? (document.querySelector(step.selector) as HTMLElement | null) : null

    if (options?.logInference) {
        const inferredResult = step.inferenceData?.autoData ? findElement(step.inferenceData) : null
        toolbarPosthogJS.capture('element inference debug', {
            selector: step.selector ?? null,
            autoDataPresent: !!step.inferenceData?.autoData,
            normalFound: !!result,
            inferenceFound: !!inferredResult,
            elementsMatch: result === inferredResult,
            ...(!!result && {
                normalElement: getElementMetadata(result),
            }),
            ...(!!inferredResult && {
                inferredElement: getElementMetadata(inferredResult),
            }),
            ...(result !== inferredResult && {
                mismatchPaths: {
                    normal: result ? getElementPath(result) : null,
                    inferred: inferredResult ? getElementPath(inferredResult) : null,
                },
            }),
        })
    }

    return result
}

export const productToursLogic = kea<productToursLogicType>([
    path(['toolbar', 'product-tours', 'productToursLogic']),

    actions({
        showButtonProductTours: true,
        hideButtonProductTours: true,

        setEditorState: (state: EditorState) => ({ state }),

        // Element selection
        startElementSelection: (stepIndex: number) => ({ stepIndex }),
        selectElement: (element: HTMLElement) => ({ element }),
        setHoverElement: (element: HTMLElement | null) => ({ element }),
        cancelSelection: true,

        // Tour selection and preview
        selectTour: (id: string | null) => ({ id }),
        previewTour: true,
        previewStep: (stepIndex: number) => ({ stepIndex }),
        startPreviewMode: true,
        stopPreview: true,

        updateRects: true,

        setLaunchedForPreview: (value: boolean) => ({ value }),
        setLaunchedForElementSelection: (value: boolean) => ({ value }),
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
            null as string | null,
            {
                selectTour: (_, { id }) => id,
            },
        ],
        editorState: [
            { mode: 'idle' } as EditorState,
            {
                setEditorState: (_, { state }) => state,
                selectTour: () => ({ mode: 'idle' }),
                hideButtonProductTours: () => ({ mode: 'idle' }),
                cancelSelection: () => ({ mode: 'idle' }),
            },
        ],
        hoverElement: [
            null as HTMLElement | null,
            {
                setHoverElement: (_, { element }) => element,
                setEditorState: () => null,
                hideButtonProductTours: () => null,
            },
        ],
        selectedElement: [
            null as HTMLElement | null,
            {
                selectElement: (_, { element }) => element,
                setEditorState: () => null,
                cancelSelection: () => null,
                hideButtonProductTours: () => null,
            },
        ],
        rectUpdateCounter: [
            0,
            {
                updateRects: (state) => state + 1,
            },
        ],
        launchedForPreview: [
            false,
            {
                setLaunchedForPreview: (_, { value }) => value,
                selectTour: () => false,
            },
        ],
        launchedForElementSelection: [
            false,
            {
                setLaunchedForElementSelection: (_, { value }) => value,
            },
        ],
    }),

    connect(() => ({
        values: [
            toolbarConfigLogic,
            ['dataAttributes', 'uiHost', 'userIntent', 'productTourId', 'productTourStepIndex', 'posthog'],
        ],
    })),

    selectors({
        selectedTour: [
            (s) => [s.selectedTourId, s.tours],
            (selectedTourId, tours): ProductTour | null => {
                if (selectedTourId) {
                    return tours.find((t: ProductTour) => t.id === selectedTourId) ?? null
                }
                return null
            },
        ],
        selectedTourSteps: [
            (s) => [s.selectedTour],
            (selectedTour): TourStep[] => {
                return (selectedTour?.content?.steps ?? []).map((step) => ({ ...step }))
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
        stepCount: [(s) => [s.selectedTourSteps], (steps) => steps.length],
    }),

    listeners(({ actions, values }) => ({
        startElementSelection: ({ stepIndex }) => {
            toolbarPosthogJS.capture(ProductTourEvent.STEP_ADDED, {
                step_type: 'element',
                step_index: stepIndex,
                tour_id: values.selectedTourId,
            })
            actions.setEditorState({ mode: 'selecting', stepIndex })
        },

        selectElement: async ({ element }) => {
            const { editorState, selectedTourId, dataAttributes, launchedForElementSelection, uiHost } = values
            if (editorState.mode !== 'selecting' || !selectedTourId) {
                return
            }

            const { stepIndex } = editorState
            const selector = elementToActionStep(element, dataAttributes).selector ?? ''
            const inferenceData = inferSelector(element)?.selector

            // Capture screenshot
            let screenshotMediaId: string | undefined
            try {
                const screenshot = await captureAndUploadElementScreenshot(element)
                screenshotMediaId = screenshot.mediaId
            } catch (e) {
                console.warn('[Product Tours] Failed to capture element screenshot:', e)
            }

            // Build the step data to save
            const stepData = {
                selector,
                inferenceData,
                screenshotMediaId,
            }

            // Save to backend
            try {
                const response = await toolbarFetch(
                    `/api/projects/@current/product_tours/${selectedTourId}/update_step_element/`,
                    'POST',
                    {
                        step_index: stepIndex,
                        ...stepData,
                    }
                )

                if (!response.ok) {
                    const error = await response.json()
                    lemonToast.error(error.detail || 'Failed to save element')
                    return
                }

                lemonToast.success('Element selected')

                // If launched specifically for element selection, close the tab
                if (launchedForElementSelection) {
                    // Small delay to show the toast
                    setTimeout(() => {
                        window.close()
                    }, 500)
                } else {
                    // Otherwise just go back to idle and reload tours
                    actions.setEditorState({ mode: 'idle' })
                    actions.loadTours()
                }
            } catch (e) {
                console.error('[Product Tours] Failed to save element:', e)
                lemonToast.error('Failed to save element')
            }
        },

        selectTour: ({ id }) => {
            if (id !== null) {
                toolbarLogic.actions.setVisibleMenu('none')
            }
        },

        previewTour: () => {
            const { selectedTour, selectedTourSteps, posthog } = values
            if (!selectedTour || !posthog?.productTours) {
                lemonToast.error('Unable to preview tour')
                return
            }

            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const productTours = posthog.productTours as any
            if (typeof productTours.previewTour !== 'function') {
                lemonToast.error('Preview requires an updated version of posthog-js')
                return
            }

            // Check if the first element step's target exists on this page
            const firstElementStep = selectedTourSteps.find((step) => step.type === 'element' && step.selector)
            if (firstElementStep && !getStepElement(firstElementStep)) {
                // eslint-disable-next-line no-alert
                alert(
                    "Can't preview tour: the first step targets an element not found on this page.\n\nNavigate to a page where this element exists, or update the selector."
                )
                return
            }

            toolbarPosthogJS.capture(ProductTourEvent.PREVIEW_STARTED, {
                tour_id: selectedTour.id,
                step_count: selectedTourSteps.length,
            })
            actions.startPreviewMode()
            toolbarLogic.actions.toggleMinimized(true)

            const tour = {
                id: `preview-${Date.now()}`,
                name: selectedTour.name || 'Preview Tour',
                type: 'product_tour' as const,
                start_date: null,
                end_date: null,
                steps: prepareStepsForRender(selectedTourSteps),
                appearance: selectedTour.content?.appearance,
            }

            productTours.previewTour(tour)
        },

        previewStep: ({ stepIndex }) => {
            const { selectedTourSteps } = values
            const step = selectedTourSteps[stepIndex]
            if (!step) {
                return
            }

            // For element steps, scroll to and highlight the element
            if (step.type === 'element') {
                const element = getStepElement(step, { logInference: true })
                if (element) {
                    element.scrollIntoView({ behavior: 'smooth', block: 'center' })
                } else {
                    lemonToast.warning('Element not found on this page')
                }
            }
        },

        stopPreview: () => {
            const { selectedTour, launchedForPreview } = values
            const isAnnouncement = selectedTour?.content?.type === 'announcement'

            if (isAnnouncement) {
                if (launchedForPreview) {
                    window.close()
                    return
                }
                actions.selectTour(null)
            }
            toolbarLogic.actions.toggleMinimized(false)
        },

        showButtonProductTours: () => {
            toolbarPosthogJS.capture('toolbar mode triggered', { mode: 'product-tours', enabled: true })
            actions.loadTours()
        },

        hideButtonProductTours: () => {
            toolbarPosthogJS.capture('toolbar mode triggered', { mode: 'product-tours', enabled: false })
        },

        loadToursSuccess: () => {
            const { userIntent, productTourId, productTourStepIndex } = values

            if (userIntent === 'edit-product-tour' && productTourId) {
                // Edit mode - select the tour and show it
                actions.selectTour(productTourId)
                toolbarConfigLogic.actions.clearUserIntent()
            } else if (userIntent === 'preview-product-tour' && productTourId) {
                // Preview mode
                actions.setLaunchedForPreview(true)
                actions.selectTour(productTourId)
                actions.previewTour()
                toolbarConfigLogic.actions.clearUserIntent()
            } else if (userIntent === 'select-product-tour-element' && productTourId) {
                // Element selection mode - select tour and start selection
                actions.setLaunchedForElementSelection(true)
                actions.selectTour(productTourId)
                const stepIndex = productTourStepIndex ?? 0
                actions.startElementSelection(stepIndex)
                toolbarConfigLogic.actions.clearUserIntent()
            }
        },
    })),

    events(({ actions, values, cache }) => ({
        afterMount: () => {
            actions.loadTours()

            // Watch for DOM changes to update highlights
            cache.mutationTimeout = null as ReturnType<typeof setTimeout> | null
            cache.mutationObserver = new MutationObserver(() => {
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
                if (values.isPreviewing) {
                    return
                }
                if (values.editorState.mode !== 'selecting') {
                    return
                }
                const target = e.target as HTMLElement
                if (target && !isToolbarElement(target)) {
                    actions.setHoverElement(target)
                }
            }

            cache.onClick = (e: MouseEvent): void => {
                // Cmd/ctrl+click always passes through
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
                    actions.cancelSelection()
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
