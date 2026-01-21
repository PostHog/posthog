import { JSONContent } from '@tiptap/core'
import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import { IconChevronRight, IconCursorClick, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { ProductTourPreview } from 'scenes/product-tours/components/ProductTourPreview'
import {
    TOUR_STEP_MAX_WIDTH,
    TOUR_STEP_MIN_WIDTH,
    getWidthValue,
} from 'scenes/product-tours/editor/ProductTourStepsEditor'
import { StepContentEditor } from 'scenes/product-tours/editor/StepContentEditor'
import { SurveyStepEditor } from 'scenes/product-tours/editor/SurveyStepEditor'
import { PositionSelector } from 'scenes/surveys/survey-appearance/SurveyAppearancePositionSelector'

import { toolbarUploadMedia } from '~/toolbar/toolbarConfigLogic'
import { ElementRect } from '~/toolbar/types'
import { elementToActionStep } from '~/toolbar/utils'
import { ProductTourProgressionTriggerType, ProductTourSurveyQuestion, ScreenPosition, SurveyPosition } from '~/types'

import { productToursLogic } from './productToursLogic'

const DEFAULT_STEP_CONTENT: JSONContent = {
    type: 'doc',
    content: [
        {
            type: 'heading',
            attrs: { level: 1 },
            content: [{ type: 'text', text: 'Step title' }],
        },
        {
            type: 'paragraph',
            content: [{ type: 'text', text: 'Describe what this element does...' }],
        },
    ],
}

type Position = 'right' | 'left' | 'top' | 'bottom'

function calculatePosition(
    targetRect: ElementRect,
    editorWidth: number,
    editorHeight: number,
    padding: number,
    preference: Position = 'right'
): { left: number; top: number } {
    const viewport = {
        width: window.innerWidth,
        height: window.innerHeight,
    }

    const spaceRight = viewport.width - (targetRect.left + targetRect.width)
    const spaceLeft = targetRect.left
    const spaceBottom = viewport.height - (targetRect.top + targetRect.height)
    const spaceTop = targetRect.top

    const fitsRight = spaceRight >= editorWidth + padding * 2
    const fitsLeft = spaceLeft >= editorWidth + padding * 2
    const fitsBottom = spaceBottom >= editorHeight + padding * 2
    const fitsTop = spaceTop >= editorHeight + padding * 2

    let position: Position = preference
    if (preference === 'right' && !fitsRight) {
        position = fitsLeft ? 'left' : fitsBottom ? 'bottom' : fitsTop ? 'top' : 'right'
    } else if (preference === 'left' && !fitsLeft) {
        position = fitsRight ? 'right' : fitsBottom ? 'bottom' : fitsTop ? 'top' : 'left'
    }

    let left: number
    let top: number

    if (position === 'right' || position === 'left') {
        left =
            position === 'right'
                ? targetRect.left + targetRect.width + padding
                : targetRect.left - editorWidth - padding

        // Try aligning top edges first
        top = targetRect.top

        // If that puts popup off screen at bottom, align bottom edges instead
        if (top + editorHeight > viewport.height - padding) {
            top = targetRect.top + targetRect.height - editorHeight
        }

        // Clamp to min padding if still off screen at top
        top = Math.max(padding, top)
    } else if (position === 'bottom') {
        left = targetRect.left
        top = targetRect.top + targetRect.height + padding
    } else {
        // top
        left = targetRect.left
        top = targetRect.top - editorHeight - padding
    }

    // Clamp horizontal to viewport edges
    const maxLeft = viewport.width - editorWidth - padding
    left = Math.max(padding, Math.min(left, maxLeft))

    return { left, top }
}

export function StepEditor({ rect, elementNotFound }: { rect?: ElementRect; elementNotFound?: boolean }): JSX.Element {
    const { editingStep, selectedElement, dataAttributes, editingStepIndex, editingStepType } =
        useValues(productToursLogic)
    const { confirmStep, cancelEditing, removeStep, changeStepElement } = useActions(productToursLogic)

    const [stepContent, setStepContent] = useState<JSONContent | null>(editingStep?.content ?? DEFAULT_STEP_CONTENT)
    const editorRef = useRef<HTMLDivElement>(null)
    const [position, setPosition] = useState<{ left: number; top: number } | null>(null)
    const [selector, setSelector] = useState('')
    const [showAdvanced, setShowAdvanced] = useState(false)
    const [useManualSelector, setUseManualSelector] = useState(editingStep?.useManualSelector ?? false)

    // Progression trigger state (for element steps)
    const [progressionTrigger, setProgressionTrigger] = useState<ProductTourProgressionTriggerType>('button')

    // Modal position state (for modal/survey steps)
    const [modalPosition, setModalPosition] = useState<ScreenPosition>(
        editingStep?.modalPosition ?? SurveyPosition.MiddleCenter
    )

    // Survey step state - managed by SurveyStepEditor
    const [surveyConfig, setSurveyConfig] = useState<ProductTourSurveyQuestion | undefined>(editingStep?.survey)

    const [editorWidth, setEditorWidth] = useState(() => getWidthValue(editingStep?.maxWidth))
    const [isResizing, setIsResizing] = useState(false)

    const isElementStep = editingStepType === 'element'
    const isModalStep = editingStepType === 'modal'
    const isSurveyStep = editingStepType === 'survey'
    const padding = 16

    const getDisabledReason = (): string | undefined => {
        if (isSurveyStep && !surveyConfig?.questionText?.trim()) {
            return 'Enter a question'
        }
        if (isElementStep && useManualSelector && !selector?.trim()) {
            return 'Enter a CSS selector'
        }
        return undefined
    }

    const handleResizeStart = useCallback(
        (e: React.MouseEvent) => {
            e.preventDefault()
            setIsResizing(true)
            const startX = e.clientX
            const startWidth = editorWidth

            const handleMouseMove = (moveEvent: MouseEvent): void => {
                const deltaX = moveEvent.clientX - startX
                const newWidth = Math.min(TOUR_STEP_MAX_WIDTH, Math.max(TOUR_STEP_MIN_WIDTH, startWidth + deltaX))
                setEditorWidth(newWidth)
            }

            const handleMouseUp = (): void => {
                setIsResizing(false)
                document.removeEventListener('mousemove', handleMouseMove)
                document.removeEventListener('mouseup', handleMouseUp)
            }

            document.addEventListener('mousemove', handleMouseMove)
            document.addEventListener('mouseup', handleMouseUp)
        },
        [editorWidth]
    )

    const handleConfirm = (): void => {
        if (isElementStep) {
            confirmStep({
                type: 'element',
                content: stepContent,
                selector,
                useManualSelector,
                maxWidth: editorWidth,
                progressionTrigger,
            })
        } else if (isSurveyStep) {
            confirmStep({
                type: 'survey',
                survey: surveyConfig!,
                modalPosition,
            })
        } else {
            confirmStep({
                type: 'modal',
                content: stepContent,
                modalPosition,
                maxWidth: editorWidth,
            })
        }
    }

    useEffect(() => {
        if (editingStep) {
            setEditorWidth(getWidthValue(editingStep.maxWidth))
        }
    }, [editingStep?.id, editingStep?.maxWidth])

    // Initialize selector, progressionTrigger, and useManualSelector from selectedElement or editingStep
    useEffect(() => {
        const newSelector = selectedElement
            ? (elementToActionStep(selectedElement, dataAttributes).selector ?? '')
            : (editingStep?.selector ?? '')

        setSelector(newSelector)
        setProgressionTrigger(editingStep?.progressionTrigger ?? 'button')
        setUseManualSelector(editingStep?.useManualSelector ?? false)
    }, [editingStep, selectedElement, dataAttributes])

    // Initialize survey config and modal position from existing step
    useEffect(() => {
        setSurveyConfig(editingStep?.survey)
        setModalPosition(editingStep?.modalPosition ?? SurveyPosition.MiddleCenter)
    }, [editingStep?.id])

    // Position element steps near target (when element is visible)
    useLayoutEffect(() => {
        if (!isModalStep && !isSurveyStep && !elementNotFound && editorRef.current && rect) {
            const editorHeight = editorRef.current.offsetHeight
            setPosition(calculatePosition(rect, editorWidth, editorHeight, padding, 'right'))
        }
    }, [rect, isModalStep, isSurveyStep, elementNotFound, editorWidth])

    // Center modal/survey steps, or element steps when element not found
    const shouldCenter = isModalStep || isSurveyStep || elementNotFound
    useLayoutEffect(() => {
        if (!shouldCenter) {
            return
        }

        const centerEditor = (): void => {
            const editorHeight = editorRef.current?.offsetHeight || 0
            setPosition({
                left: Math.max(padding, (window.innerWidth - editorWidth) / 2),
                top: Math.max(padding, (window.innerHeight - editorHeight) / 2),
            })
        }

        centerEditor()

        const observer = new ResizeObserver(centerEditor)
        if (editorRef.current) {
            observer.observe(editorRef.current)
        }

        window.addEventListener('resize', centerEditor)

        return () => {
            observer.disconnect()
            window.removeEventListener('resize', centerEditor)
        }
    }, [shouldCenter, editorWidth])

    // Update content state when editing a different step
    useEffect(() => {
        setStepContent(editingStep?.content ?? DEFAULT_STEP_CONTENT)
    }, [editingStep?.id])

    const style: React.CSSProperties = {
        position: 'fixed',
        width: editorWidth,
        visibility: position ? 'visible' : 'hidden',
        ...(position ?? { left: 0, top: 0 }),
    }

    const stepTypeLabel = isSurveyStep ? 'survey' : isModalStep ? 'modal' : 'element'
    const actionLabel = editingStep
        ? `Editing step ${editingStepIndex! + 1} (${stepTypeLabel})`
        : `Adding ${stepTypeLabel} step`

    return (
        <div
            ref={editorRef}
            className="bg-white rounded-lg space-y-0 overflow-hidden toolbar-animate-slide-up"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                ...style,
                zIndex: 2147483020,
                pointerEvents: 'auto',
                border: '1px solid #e5e7eb',
                boxShadow: '0 4px 24px rgba(0, 0, 0, 0.15), 0 0 0 1px rgba(0, 0, 0, 0.05)',
            }}
        >
            <div
                onMouseDown={handleResizeStart}
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    position: 'absolute',
                    top: 0,
                    right: -4,
                    width: 8,
                    height: '100%',
                    cursor: 'ew-resize',
                    zIndex: 10,
                }}
                title={`Width: ${editorWidth}px (drag to resize)`}
            />
            {isResizing && (
                <div
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        position: 'absolute',
                        top: 0,
                        right: 0,
                        width: 3,
                        height: '100%',
                        backgroundColor: '#1d4aff',
                        borderRadius: '0 4px 4px 0',
                    }}
                />
            )}
            {/* Header showing current action */}
            <div
                className="text-white text-xs font-medium px-3 py-1.5"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ backgroundColor: '#1d4aff' }}
            >
                {actionLabel}
            </div>

            {/* Warning when element not found */}
            {elementNotFound && (
                <div className="px-3 py-2 bg-warning-highlight text-warning-dark text-xs">
                    Target element not visible on this page
                </div>
            )}

            <div className="p-4 space-y-3">
                {/* Rich text editor for non-survey steps */}
                {!isSurveyStep && (
                    <StepContentEditor
                        content={stepContent}
                        onChange={setStepContent}
                        uploadImage={toolbarUploadMedia}
                        placeholder="Type '/' for commands, or start writing..."
                        compact
                    />
                )}

                {/* Survey configuration */}
                {isSurveyStep && (
                    <div className="space-y-3">
                        <SurveyStepEditor survey={surveyConfig} onChange={setSurveyConfig} />

                        {/* Survey preview */}
                        <div className="pt-2">
                            <div className="text-[10px] text-muted uppercase tracking-wide mb-2">Preview</div>
                            {surveyConfig && (
                                <ProductTourPreview
                                    step={{
                                        id: 'preview',
                                        type: 'survey',
                                        content: null,
                                        survey: surveyConfig,
                                        progressionTrigger: 'button',
                                    }}
                                    prepareStep={false}
                                />
                            )}
                        </div>
                    </div>
                )}

                {/* Element step: change element button */}
                {isElementStep && editingStep && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconCursorClick />}
                        onClick={() => changeStepElement()}
                        fullWidth
                    >
                        Change element
                    </LemonButton>
                )}

                {/* Advanced section */}
                <div className="space-y-1">
                    <button
                        type="button"
                        onClick={() => setShowAdvanced(!showAdvanced)}
                        className="flex items-center gap-1 text-xs text-muted hover:text-default transition-colors"
                    >
                        <IconChevronRight
                            className={`w-3 h-3 transition-transform ${showAdvanced ? 'rotate-90' : ''}`}
                        />
                        Advanced
                    </button>
                    {showAdvanced && (
                        <div className="space-y-3 pt-1">
                            {isElementStep && (
                                <div className="space-y-2">
                                    <label className="text-xs font-medium">Element targeting</label>
                                    <LemonSegmentedButton
                                        value={useManualSelector ? 'css' : 'auto'}
                                        onChange={(value) => {
                                            if (value === 'auto' && useManualSelector) {
                                                // switching from auto -> manual means you must re-select
                                                // your element. when you switch from manual -> auto, we wipe
                                                // inference data to avoid getting into weird states
                                                changeStepElement()
                                            }
                                            setUseManualSelector(value === 'css')
                                        }}
                                        options={[
                                            { value: 'auto', label: 'Auto' },
                                            { value: 'css', label: 'CSS selector' },
                                        ]}
                                        size="xsmall"
                                    />
                                    {!useManualSelector && (
                                        <p className="text-[10px] text-muted">
                                            PostHog automatically finds the element using stored attributes
                                        </p>
                                    )}
                                    {useManualSelector && (
                                        <LemonInput
                                            value={selector}
                                            onChange={setSelector}
                                            placeholder="#my-button or [data-testid='login']"
                                            size="small"
                                            fullWidth
                                            className="font-mono text-xs"
                                        />
                                    )}
                                </div>
                            )}
                            {isElementStep && (
                                <div className="space-y-2">
                                    <label className="text-xs font-medium">Advance action</label>
                                    <LemonSegmentedButton
                                        value={progressionTrigger}
                                        onChange={setProgressionTrigger}
                                        options={[
                                            { value: 'button', label: 'Next button' },
                                            { value: 'click', label: 'Element click' },
                                        ]}
                                        size="xsmall"
                                    />
                                    <p className="text-[10px] text-muted">
                                        {progressionTrigger === 'button' && 'Display a "Next" button in the tour step'}
                                        {progressionTrigger === 'click' &&
                                            'Users click the target element to go to the next step'}
                                    </p>
                                </div>
                            )}
                            {!isElementStep && (
                                <div className="space-y-1">
                                    <label className="text-xs font-medium">Position</label>
                                    <PositionSelector value={modalPosition} onChange={setModalPosition} toolbar />
                                </div>
                            )}
                        </div>
                    )}
                </div>

                <div className="flex items-center justify-between">
                    <div className="flex gap-2 pt-1">
                        <LemonButton type="secondary" size="small" onClick={() => cancelEditing()}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={handleConfirm}
                            disabledReason={getDisabledReason()}
                        >
                            Done
                        </LemonButton>
                    </div>
                    <LemonButton
                        icon={<IconTrash />}
                        type="secondary"
                        status="danger"
                        size="small"
                        onClick={() => {
                            if (editingStepIndex !== null) {
                                removeStep(editingStepIndex)
                            }
                        }}
                        tooltip="Delete this step"
                    />
                </div>
            </div>
        </div>
    )
}
