import { JSONContent } from '@tiptap/core'
import { useActions, useValues } from 'kea'
import { renderSurveysPreview } from 'posthog-js/dist/surveys-preview'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { IconChevronRight, IconCursorClick, IconTrash } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { ElementRect } from '~/toolbar/types'
import { elementToActionStep } from '~/toolbar/utils'
import {
    ProductTourProgressionTriggerType,
    ProductTourSurveyQuestion,
    ProductTourSurveyQuestionType,
    SurveyPosition,
    SurveyQuestionType,
    SurveyType,
} from '~/types'

import { ToolbarEditor, ToolbarRichTextEditor } from './ToolbarRichTextEditor'
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

const DEFAULT_RATING_QUESTION = 'How helpful was this tour?'
const DEFAULT_OPEN_QUESTION = 'Any feedback on this tour?'

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

    const [richEditor, setRichEditor] = useState<ToolbarEditor | null>(null)
    const editorRef = useRef<HTMLDivElement>(null)
    const surveyPreviewRef = useRef<HTMLDivElement>(null)
    const [position, setPosition] = useState<{ left: number; top: number } | null>(null)
    const [selector, setSelector] = useState('')
    const [showAdvanced, setShowAdvanced] = useState(false)

    // Progression trigger state (for element steps)
    const [progressionTrigger, setProgressionTrigger] = useState<ProductTourProgressionTriggerType>('button')

    // Survey step state
    const [surveyType, setSurveyType] = useState<ProductTourSurveyQuestionType>('open')
    const [questionText, setQuestionText] = useState('')
    const [ratingDisplay, setRatingDisplay] = useState<'emoji' | 'number'>('emoji')
    const [ratingScale, setRatingScale] = useState<3 | 5 | 10>(5)
    const [lowerBoundLabel, setLowerBoundLabel] = useState('Not at all')
    const [upperBoundLabel, setUpperBoundLabel] = useState('Very much')

    const isElementStep = editingStepType === 'element'
    const isModalStep = editingStepType === 'modal'
    const isSurveyStep = editingStepType === 'survey'
    const editorWidth = isSurveyStep ? 360 : 320
    const padding = 16

    // Initialize selector and progressionTrigger from selectedElement or editingStep
    useEffect(() => {
        if (selectedElement) {
            // Fresh element selection (new step OR changing element) - always derive from element
            const actionStep = elementToActionStep(selectedElement, dataAttributes)
            setSelector(actionStep.selector ?? '')
            // Preserve progressionTrigger if editing existing step, otherwise default to button
            setProgressionTrigger(editingStep?.progressionTrigger ?? 'button')
        } else if (editingStep) {
            // Existing step with no new selection - use saved values
            setSelector(editingStep.selector ?? '')
            setProgressionTrigger(editingStep.progressionTrigger ?? 'button')
        } else {
            // New modal/survey step - no selector
            setSelector('')
            setProgressionTrigger('button')
        }
    }, [editingStep, selectedElement, dataAttributes])

    // Initialize survey state from existing step
    useEffect(() => {
        if (editingStep?.survey) {
            setSurveyType(editingStep.survey.type)
            setQuestionText(editingStep.survey.questionText)
            if (editingStep.survey.display) {
                setRatingDisplay(editingStep.survey.display)
            }
            if (editingStep.survey.scale) {
                setRatingScale(editingStep.survey.scale)
            }
            if (editingStep.survey.lowerBoundLabel) {
                setLowerBoundLabel(editingStep.survey.lowerBoundLabel)
            }
            if (editingStep.survey.upperBoundLabel) {
                setUpperBoundLabel(editingStep.survey.upperBoundLabel)
            }
        } else if (isSurveyStep) {
            // Reset to defaults for new survey step
            setSurveyType('open')
            setQuestionText(DEFAULT_OPEN_QUESTION)
            setRatingDisplay('emoji')
            setRatingScale(5)
            setLowerBoundLabel('Not at all')
            setUpperBoundLabel('Very much')
        }
    }, [editingStep, isSurveyStep])

    // Update scale when display type changes to ensure valid combination
    useEffect(() => {
        if (ratingDisplay === 'emoji' && ratingScale === 10) {
            setRatingScale(5) // Emoji doesn't support 10
        } else if (ratingDisplay === 'number' && ratingScale === 3) {
            setRatingScale(5) // Number doesn't support 3
        }
    }, [ratingDisplay, ratingScale])

    // Update question text when switching types (if using default)
    useEffect(() => {
        if (!editingStep?.survey) {
            // Only auto-update if this is a new survey step
            if (surveyType === 'rating' && questionText === DEFAULT_OPEN_QUESTION) {
                setQuestionText(DEFAULT_RATING_QUESTION)
            } else if (surveyType === 'open' && questionText === DEFAULT_RATING_QUESTION) {
                setQuestionText(DEFAULT_OPEN_QUESTION)
            }
        }
    }, [surveyType, editingStep, questionText])

    // Build preview survey object for rendering
    const previewSurvey = useMemo(() => {
        const displayQuestion =
            questionText || (surveyType === 'rating' ? DEFAULT_RATING_QUESTION : DEFAULT_OPEN_QUESTION)

        const question =
            surveyType === 'rating'
                ? {
                      type: SurveyQuestionType.Rating,
                      question: displayQuestion,
                      display: ratingDisplay,
                      scale: ratingScale as 3 | 5 | 7 | 10,
                      lowerBoundLabel,
                      upperBoundLabel,
                      optional: false,
                      skipSubmitButton: true, // Auto-submit on selection
                  }
                : {
                      type: SurveyQuestionType.Open,
                      question: displayQuestion,
                      optional: true,
                  }

        return {
            id: 'preview',
            name: 'Survey Preview',
            type: SurveyType.Popover,
            questions: [question],
            appearance: {
                backgroundColor: '#ffffff',
                submitButtonColor: '#1d4aff',
                submitButtonTextColor: '#ffffff',
                whiteLabel: true,
                displayThankYouMessage: false,
                position: SurveyPosition.MiddleCenter,
                hideCancelButton: true,
                maxWidth: '100%',
            },
        }
    }, [surveyType, questionText, ratingDisplay, ratingScale, lowerBoundLabel, upperBoundLabel])

    // Render survey preview
    useEffect(() => {
        if (isSurveyStep && surveyPreviewRef.current) {
            renderSurveysPreview({
                survey: previewSurvey,
                parentElement: surveyPreviewRef.current,
                previewPageIndex: 0,
                positionStyles: {
                    position: 'relative',
                    left: 'unset',
                    right: 'unset',
                    top: 'unset',
                    bottom: 'unset',
                    transform: 'unset',
                    maxWidth: '100%',
                },
            })
        }
    }, [isSurveyStep, previewSurvey])

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

    // Update editor when editing a different step
    useLayoutEffect(() => {
        if (richEditor) {
            richEditor.setContent(editingStep?.content ?? DEFAULT_STEP_CONTENT)
        }
    }, [editingStep, richEditor])

    const getContent = (): JSONContent | null => {
        if (!richEditor) {
            return null
        }
        return richEditor.isEmpty() ? null : richEditor.getJSON()
    }

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

    // Build survey config for confirmStep
    const getSurveyConfig = (): ProductTourSurveyQuestion | undefined => {
        if (!isSurveyStep) {
            return undefined
        }
        return {
            type: surveyType,
            questionText,
            ...(surveyType === 'rating'
                ? {
                      display: ratingDisplay,
                      scale: ratingScale,
                      lowerBoundLabel,
                      upperBoundLabel,
                  }
                : {}),
        }
    }

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
                    <ToolbarRichTextEditor
                        initialContent={editingStep?.content ?? DEFAULT_STEP_CONTENT}
                        onCreate={setRichEditor}
                        minRows={3}
                    />
                )}

                {/* Survey configuration - just question text + type */}
                {isSurveyStep && (
                    <div className="space-y-3">
                        {/* Question type toggle */}
                        <LemonSegmentedButton
                            size="small"
                            fullWidth
                            value={surveyType}
                            onChange={(value) => setSurveyType(value as ProductTourSurveyQuestionType)}
                            options={[
                                { value: 'open', label: 'Open text' },
                                { value: 'rating', label: 'Rating' },
                            ]}
                        />

                        {/* Question text */}
                        <div className="space-y-1">
                            <label className="text-xs font-medium">Question</label>
                            <LemonInput
                                value={questionText}
                                onChange={setQuestionText}
                                placeholder={surveyType === 'rating' ? DEFAULT_RATING_QUESTION : DEFAULT_OPEN_QUESTION}
                                size="small"
                                fullWidth
                            />
                        </div>

                        {/* Rating-specific options */}
                        {surveyType === 'rating' && (
                            <div className="space-y-2">
                                <div className="flex gap-3 items-center">
                                    <div className="flex gap-1.5 items-center">
                                        <span className="text-xs text-muted">Type:</span>
                                        <LemonSegmentedButton
                                            size="xsmall"
                                            value={ratingDisplay}
                                            onChange={(value) => setRatingDisplay(value as 'emoji' | 'number')}
                                            options={[
                                                { value: 'emoji', label: 'Emoji' },
                                                { value: 'number', label: 'Number' },
                                            ]}
                                        />
                                    </div>
                                    <div className="flex gap-1.5 items-center">
                                        <span className="text-xs text-muted">Scale:</span>
                                        <LemonSegmentedButton
                                            size="xsmall"
                                            value={ratingScale}
                                            onChange={(value) => setRatingScale(value as 3 | 5 | 10)}
                                            options={
                                                ratingDisplay === 'emoji'
                                                    ? [
                                                          { value: 3, label: '1-3' },
                                                          { value: 5, label: '1-5' },
                                                      ]
                                                    : [
                                                          { value: 5, label: '1-5' },
                                                          { value: 10, label: '0-10' },
                                                      ]
                                            }
                                        />
                                    </div>
                                </div>
                                <div className="flex gap-2">
                                    <div className="flex-1 space-y-1">
                                        <label className="text-xs text-muted">Low label</label>
                                        <LemonInput
                                            size="small"
                                            value={lowerBoundLabel}
                                            onChange={setLowerBoundLabel}
                                            placeholder="Not at all"
                                        />
                                    </div>
                                    <div className="flex-1 space-y-1">
                                        <label className="text-xs text-muted">High label</label>
                                        <LemonInput
                                            size="small"
                                            value={upperBoundLabel}
                                            onChange={setUpperBoundLabel}
                                            placeholder="Very much"
                                        />
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Survey preview */}
                        <div className="pt-2">
                            <div className="text-[10px] text-muted uppercase tracking-wide mb-2">Preview</div>
                            <div
                                ref={surveyPreviewRef}
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ minHeight: 100 }}
                            />
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

                {/* Advanced section - only for element/modal steps */}
                {!isSurveyStep && (
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
                                    <div className="space-y-1">
                                        <label className="text-xs font-medium">CSS selector</label>
                                        <LemonInput
                                            value={selector}
                                            onChange={setSelector}
                                            placeholder="CSS selector (e.g., #my-button)"
                                            size="small"
                                            fullWidth
                                            className="font-mono text-xs"
                                        />
                                    </div>
                                )}
                                {isElementStep && (
                                    <div className="space-y-1">
                                        <label className="text-xs font-medium">Advance action</label>
                                        <LemonRadio
                                            value={progressionTrigger}
                                            onChange={setProgressionTrigger}
                                            options={[
                                                { value: 'button', label: 'Next button' },
                                                { value: 'click', label: 'Element click' },
                                            ]}
                                            orientation="horizontal"
                                        />
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                )}

                <div className="flex items-center justify-between">
                    <div className="flex gap-2 pt-1">
                        <LemonButton type="secondary" size="small" onClick={() => cancelEditing()}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() =>
                                confirmStep(
                                    getContent(),
                                    isElementStep ? selector : undefined,
                                    getSurveyConfig(),
                                    isElementStep ? progressionTrigger : undefined
                                )
                            }
                            disabledReason={isSurveyStep && !questionText.trim() ? 'Enter a question' : undefined}
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
