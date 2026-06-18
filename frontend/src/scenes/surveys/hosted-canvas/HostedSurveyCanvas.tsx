import './HostedSurveyCanvas.scss'

import { DndContext, DragEndEvent } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { type CSSProperties } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'

import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { defaultSurveyAppearance } from 'scenes/surveys/constants'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { sanitizeHTML } from 'scenes/surveys/utils'

import {
    type MultipleSurveyQuestion,
    type RatingSurveyQuestion,
    type Survey,
    type SurveyAppearance,
    type SurveyQuestion,
    SurveyQuestionType,
} from '~/types'

import { type NewSurvey } from '../constants'
import { InlineEditable } from './InlineEditable'

const RATING_EMOJI_PREVIEW = ['\u{1F621}', '\u{1F641}', '\u{1F610}', '\u{1F642}', '\u{1F60D}']

function getLuminance(color: string | undefined): number | null {
    if (!color) {
        return null
    }

    let hex = color.trim().toLowerCase()
    if (hex === 'white') {
        hex = '#ffffff'
    } else if (hex === 'black') {
        hex = '#000000'
    }

    if (!hex.startsWith('#')) {
        return null
    }
    if (hex.length === 4) {
        hex = `#${hex[1]}${hex[1]}${hex[2]}${hex[2]}${hex[3]}${hex[3]}`
    }
    if (hex.length !== 7) {
        return null
    }

    const red = parseInt(hex.slice(1, 3), 16) / 255
    const green = parseInt(hex.slice(3, 5), 16) / 255
    const blue = parseInt(hex.slice(5, 7), 16) / 255
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue
}

function getContrastingTextColor(background: string | undefined): string | null {
    const luminance = getLuminance(background)
    if (luminance === null) {
        return null
    }
    return luminance > 0.55 ? '#111111' : '#ffffff'
}

function buildCanvasAppearance(survey: Survey | NewSurvey): SurveyAppearance {
    return {
        ...defaultSurveyAppearance,
        backgroundColor: '#ffffff',
        borderColor: 'rgba(17, 17, 17, 0.10)',
        borderRadius: '10px',
        submitButtonColor: '#111111',
        submitButtonTextColor: '#ffffff',
        ratingButtonColor: '#ffffff',
        ratingButtonActiveColor: '#111111',
        inputBackground: '#ffffff',
        textSubtleColor: '#6b6b6b',
        ...survey.appearance,
        hideCancelButton: true,
        surveyPopupDelaySeconds: undefined,
    }
}

interface CanvasCSSProperties extends CSSProperties {
    '--ph-survey-progress-value': string
    '--ph-survey-page-background': string
    '--ph-survey-page-text': string
    '--ph-survey-page-text-subtle': string
    '--ph-survey-page-progress-bar': string
    '--ph-survey-page-progress-track': string
    '--ph-survey-pill-background': string
    '--ph-survey-card-shadow': string
    '--ph-survey-input-background': string
    '--ph-survey-background-color': string
    '--ph-survey-border-color': string
    '--ph-survey-border-radius': string
    '--ph-survey-text-primary-color': string
    '--ph-survey-input-text-color': string
    '--ph-survey-text-subtle-color': string
    '--ph-survey-submit-button-color': string
    '--ph-survey-submit-button-text-color': string
    '--ph-survey-rating-bg-color': string
    '--ph-survey-rating-text-color': string
    '--ph-survey-rating-active-bg-color': string
    '--ph-survey-rating-active-text-color': string
}

function buildCanvasStyles(appearance: SurveyAppearance, progress: number): CanvasCSSProperties {
    const cardBg = appearance.inputBackground || appearance.backgroundColor || '#ffffff'
    const primaryText =
        appearance.textColor || appearance.inputTextColor || getContrastingTextColor(cardBg) || '#111111'
    const submitButtonColor = appearance.submitButtonColor || '#111111'
    const ratingButtonColor = appearance.ratingButtonColor || cardBg
    const ratingActiveColor = appearance.ratingButtonActiveColor || submitButtonColor
    return {
        '--ph-survey-progress-value': `${progress}%`,
        '--ph-survey-page-background': appearance.backgroundColor || '#ffffff',
        '--ph-survey-page-text': primaryText,
        '--ph-survey-page-text-subtle': appearance.textSubtleColor || '#6b6b6b',
        '--ph-survey-page-progress-bar': submitButtonColor,
        '--ph-survey-page-progress-track': 'rgba(17, 17, 17, 0.08)',
        // hosted-survey.css uses this for the footer-branding pill background;
        // without it the pill renders transparent against the survey card.
        '--ph-survey-pill-background': 'rgba(255, 255, 255, 0.7)',
        '--ph-survey-card-shadow': '0 1px 2px rgba(17, 17, 17, 0.04), 0 2px 8px rgba(17, 17, 17, 0.04)',
        '--ph-survey-input-background': cardBg,
        '--ph-survey-background-color': cardBg,
        '--ph-survey-border-color': appearance.borderColor || 'rgba(17, 17, 17, 0.10)',
        '--ph-survey-border-radius': appearance.borderRadius || '10px',
        '--ph-survey-text-primary-color': primaryText,
        '--ph-survey-input-text-color': primaryText,
        '--ph-survey-text-subtle-color': appearance.textSubtleColor || '#6b6b6b',
        '--ph-survey-submit-button-color': submitButtonColor,
        '--ph-survey-submit-button-text-color':
            appearance.submitButtonTextColor || getContrastingTextColor(submitButtonColor) || '#ffffff',
        '--ph-survey-rating-bg-color': ratingButtonColor,
        '--ph-survey-rating-text-color': getContrastingTextColor(ratingButtonColor) || primaryText,
        '--ph-survey-rating-active-bg-color': ratingActiveColor,
        '--ph-survey-rating-active-text-color': getContrastingTextColor(ratingActiveColor) || '#ffffff',
    }
}

function getProgress(survey: Survey | NewSurvey, pageIndex: number): number {
    if (pageIndex >= survey.questions.length) {
        return 100
    }
    if (survey.questions.length === 0) {
        return 0
    }
    return Math.round(((pageIndex + 1) / survey.questions.length) * 100)
}

interface HostedSurveyCanvasProps {
    survey: Survey | NewSurvey
    activePageIndex: number
    /** True when active page is the confirmation/thank-you screen. */
    isConfirmation: boolean
    /** Mobile vs desktop frame for visual context. */
    viewport: 'desktop' | 'mobile'
}

export function HostedSurveyCanvas({
    survey,
    activePageIndex,
    isConfirmation,
    viewport,
}: HostedSurveyCanvasProps): JSX.Element {
    const appearance = buildCanvasAppearance(survey)
    const progress = getProgress(survey, activePageIndex)
    const styles = buildCanvasStyles(appearance, progress)
    const activeQuestion = survey.questions[activePageIndex] as SurveyQuestion | undefined
    const frameClassName =
        viewport === 'mobile'
            ? 'PostHogHostedSurvey HostedSurveyPreviewFrame HostedSurveyPreviewFrame--mobile'
            : 'PostHogHostedSurvey HostedSurveyPreviewFrame'

    return (
        <div className="HostedSurveyCanvasStage">
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div className={frameClassName} style={styles}>
                <div className="survey-progress-wrap">
                    <div
                        className="survey-progress-track"
                        role="progressbar"
                        aria-label="Survey progress"
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={progress}
                    >
                        <span className="survey-progress-bar" />
                    </div>
                </div>
                <div className="survey-stage">
                    <div className="posthog-survey-container">
                        {isConfirmation ? (
                            <ConfirmationCanvas survey={survey} />
                        ) : activeQuestion ? (
                            <QuestionCanvas question={activeQuestion} index={activePageIndex} />
                        ) : null}
                    </div>
                </div>
                {!appearance.whiteLabel ? <div className="footer-branding">Survey by PostHog</div> : null}
            </div>
        </div>
    )
}

function QuestionCanvas({ question, index }: { question: SurveyQuestion; index: number }): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)

    // Surveys union typing makes a strict per-key updater painful — accept arbitrary
    // values here. Each caller already constrains the value to the matching question
    // type, and the survey form schema validates downstream.
    const updateField = (key: string, value: unknown): void => {
        const next = survey.questions.map((q, idx) => (idx === index ? { ...q, [key]: value } : q))
        setSurveyValue('questions', next)
    }

    const isChoiceQuestion =
        question.type === SurveyQuestionType.SingleChoice || question.type === SurveyQuestionType.MultipleChoice
    const choiceQuestion = isChoiceQuestion ? (question as MultipleSurveyQuestion) : null

    const commitChoices = (choices: string[]): void => {
        if (!choiceQuestion) {
            return
        }
        updateField('choices', choices)
    }

    const updateChoice = (choiceIndex: number, value: string): void => {
        if (!choiceQuestion) {
            return
        }
        const choices = [...(choiceQuestion.choices || [])]
        choices[choiceIndex] = value
        commitChoices(choices)
    }

    const deleteChoice = (choiceIndex: number): void => {
        if (!choiceQuestion) {
            return
        }
        const choices = choiceQuestion.choices || []
        const isDeletingOpen = !!choiceQuestion.hasOpenChoice && choiceIndex === choices.length - 1
        const remaining = choices.filter((_, i) => i !== choiceIndex)
        if (isDeletingOpen) {
            // Deleting the open-ended option also unsets the flag so the bookkeeping stays consistent.
            const next = survey.questions.map((q, idx) =>
                idx === index ? { ...q, choices: remaining, hasOpenChoice: false } : q
            )
            setSurveyValue('questions', next)
            return
        }
        commitChoices(remaining)
    }

    const addChoice = (): void => {
        if (!choiceQuestion) {
            return
        }
        const choices = choiceQuestion.choices || []
        if (choiceQuestion.hasOpenChoice && choices.length > 0) {
            // Insert before the trailing open-ended choice so it stays last.
            const head = choices.slice(0, -1)
            const open = choices[choices.length - 1]
            commitChoices([...head, 'New option', open])
            return
        }
        commitChoices([...choices, 'New option'])
    }

    const reorderChoices = (from: number, to: number): void => {
        if (!choiceQuestion) {
            return
        }
        const choices = [...(choiceQuestion.choices || [])]
        // The open-ended option must always remain last — guard against accidental swaps.
        const lastIndex = choices.length - 1
        if (choiceQuestion.hasOpenChoice && (from === lastIndex || to === lastIndex)) {
            return
        }
        const [moved] = choices.splice(from, 1)
        choices.splice(to, 0, moved)
        commitChoices(choices)
    }

    const buttonTextDefault = question.type === SurveyQuestionType.Link ? 'Continue' : 'Submit'

    return (
        <form className="survey-form" name="surveyForm" onSubmit={(event) => event.preventDefault()}>
            <div className="survey-box" data-question-index={index}>
                <div className="question-container">
                    <div>
                        <InlineEditable
                            as="h1"
                            className="survey-question"
                            value={question.question}
                            onChange={(value) => updateField('question', value)}
                            placeholder="Untitled question"
                            ariaLabel="Question text"
                            multiline
                            data-attr={`canvas-question-${index}-text`}
                        />
                        {question.descriptionContentType === 'html' && question.description ? (
                            // Keep HTML descriptions rendered (canvas v1 doesn't inline-edit HTML).
                            <div
                                className="survey-question-description"
                                dangerouslySetInnerHTML={{ __html: sanitizeHTML(question.description) }}
                            />
                        ) : (
                            <InlineEditable
                                as="p"
                                className="survey-question-description"
                                value={question.description || ''}
                                onChange={(value) => updateField('description', value)}
                                placeholder="Add a description (optional)"
                                ariaLabel="Question description"
                                multiline
                                data-attr={`canvas-question-${index}-description`}
                            />
                        )}
                    </div>

                    {question.type === SurveyQuestionType.Open ? (
                        <textarea value="" placeholder="Respondent will type here…" readOnly aria-hidden />
                    ) : null}

                    {question.type === SurveyQuestionType.Link ? (
                        <InlineEditable
                            as="span"
                            value={question.link || ''}
                            onChange={(value) => updateField('link', value)}
                            placeholder="https://example.com"
                            ariaLabel="Destination URL"
                            data-attr={`canvas-question-${index}-link`}
                        />
                    ) : null}

                    {choiceQuestion && (
                        <ChoicesEditor
                            question={choiceQuestion}
                            questionIndex={index}
                            onChoiceChange={updateChoice}
                            onChoiceDelete={deleteChoice}
                            onChoiceAdd={addChoice}
                            onChoiceReorder={reorderChoices}
                        />
                    )}

                    {question.type === SurveyQuestionType.Rating ? (
                        <RatingCanvas
                            question={question as RatingSurveyQuestion}
                            onLowerBoundChange={(value) => updateField('lowerBoundLabel', value)}
                            onUpperBoundChange={(value) => updateField('upperBoundLabel', value)}
                        />
                    ) : null}

                    <div className="bottom-section">
                        <InlineEditable
                            as="span"
                            value={question.buttonText || ''}
                            onChange={(value) => updateField('buttonText', value)}
                            placeholder={buttonTextDefault}
                            ariaLabel="Submit button label"
                            className="form-submit"
                            data-attr={`canvas-question-${index}-button-text`}
                        />
                        <KeyboardHints questionType={question.type} />
                    </div>
                </div>
            </div>
        </form>
    )
}

// Keyboard hint chips next to the submit button. Mirrors the per-question
// hint set rendered by `posthog/templates/surveys/public_survey.html` so the
// canvas matches what respondents actually see.
function KeyboardHints({ questionType }: { questionType: SurveyQuestionType }): JSX.Element {
    const chips: { kbd: string; label: string }[] = [{ kbd: '\u21B5', label: 'submit' }]

    if (questionType === SurveyQuestionType.Open) {
        chips.push({ kbd: '\u21E7 \u21B5', label: 'new line' })
    } else if (questionType === SurveyQuestionType.SingleChoice) {
        chips.push({ kbd: '\u2191 \u2193', label: 'select' })
    } else if (questionType === SurveyQuestionType.MultipleChoice) {
        chips.push({ kbd: '\u2191 \u2193', label: 'select' })
        chips.push({ kbd: 'Space', label: 'toggle' })
    } else if (questionType === SurveyQuestionType.Rating) {
        chips.push({ kbd: '\u2190 \u2192', label: 'select' })
    }

    return (
        <span className="survey-keyhint" aria-hidden>
            {chips.map(({ kbd, label }) => (
                <span className="survey-keyhint-row" key={label}>
                    <kbd className="survey-kbd">{kbd}</kbd>
                    <span className="survey-keyhint-label">{label}</span>
                </span>
            ))}
        </span>
    )
}

function ChoicesEditor({
    question,
    questionIndex,
    onChoiceChange,
    onChoiceDelete,
    onChoiceAdd,
    onChoiceReorder,
}: {
    question: MultipleSurveyQuestion
    questionIndex: number
    onChoiceChange: (choiceIndex: number, value: string) => void
    onChoiceDelete: (choiceIndex: number) => void
    onChoiceAdd: () => void
    onChoiceReorder: (from: number, to: number) => void
}): JSX.Element {
    const choices = question.choices || []
    const lastIndex = choices.length - 1
    const choiceItemIds = choices.map((_, idx) => idx.toString())

    const handleDragEnd = ({ active, over }: DragEndEvent): void => {
        if (!over || active.id === over.id) {
            return
        }
        const from = choiceItemIds.indexOf(active.id.toString())
        const to = choiceItemIds.indexOf(over.id.toString())
        if (from < 0 || to < 0) {
            return
        }
        onChoiceReorder(from, to)
    }

    return (
        <fieldset>
            <legend className="sr-only">{question.question}</legend>
            <div className="multiple-choice-options">
                <DndContext onDragEnd={handleDragEnd}>
                    <SortableContext items={choiceItemIds} strategy={verticalListSortingStrategy}>
                        {choices.map((choice, choiceIndex) => {
                            // When hasOpenChoice is enabled, the LAST choice renders with a ":" suffix and
                            // an adjacent text input — mirroring what respondents see in the shipped survey.
                            const isOpenChoice = !!question.hasOpenChoice && choiceIndex === lastIndex
                            return (
                                <ChoiceRow
                                    key={choiceIndex}
                                    id={choiceIndex.toString()}
                                    choice={choice}
                                    choiceIndex={choiceIndex}
                                    isOpenChoice={isOpenChoice}
                                    isCheckbox={question.type === SurveyQuestionType.MultipleChoice}
                                    canReorder={choices.length > 1 && !isOpenChoice}
                                    canDelete={choices.length > 1}
                                    questionIndex={questionIndex}
                                    onChoiceChange={onChoiceChange}
                                    onChoiceDelete={onChoiceDelete}
                                />
                            )
                        })}
                    </SortableContext>
                </DndContext>
                <button
                    type="button"
                    className="HostedSurveyCanvasAddChoice"
                    onClick={onChoiceAdd}
                    data-attr={`canvas-question-${questionIndex}-add-choice`}
                >
                    <IconPlus />
                    Add choice
                </button>
            </div>
        </fieldset>
    )
}

function ChoiceRow({
    id,
    choice,
    choiceIndex,
    isOpenChoice,
    isCheckbox,
    canReorder,
    canDelete,
    questionIndex,
    onChoiceChange,
    onChoiceDelete,
}: {
    id: string
    choice: string
    choiceIndex: number
    isOpenChoice: boolean
    isCheckbox: boolean
    canReorder: boolean
    canDelete: boolean
    questionIndex: number
    onChoiceChange: (choiceIndex: number, value: string) => void
    onChoiceDelete: (choiceIndex: number) => void
}): JSX.Element {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id,
        animateLayoutChanges: () => false,
    })

    return (
        <div
            ref={setNodeRef}
            {...attributes}
            className={`HostedSurveyCanvasChoice ${isDragging ? 'HostedSurveyCanvasChoice--dragging' : ''}`}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                transform: CSS.Translate.toString(transform),
                transition,
            }}
        >
            <span
                className={`HostedSurveyCanvasChoice__grip ${canReorder ? '' : 'HostedSurveyCanvasChoice__grip--locked'}`}
                aria-label={canReorder ? `Reorder choice ${choiceIndex + 1}` : 'Open-ended choice stays last'}
                {...(canReorder ? listeners : {})}
            >
                <SortableDragIcon />
            </span>
            <label className={isOpenChoice ? 'choice-option-open' : undefined}>
                <div className="response-choice">
                    <input
                        type={isCheckbox ? 'checkbox' : 'radio'}
                        checked={false}
                        onChange={() => {}}
                        aria-hidden
                        tabIndex={-1}
                    />
                    <span className="HostedSurveyCanvasChoice__label">
                        <InlineEditable
                            value={choice}
                            onChange={(value) => onChoiceChange(choiceIndex, value)}
                            placeholder={`Choice ${choiceIndex + 1}`}
                            ariaLabel={`Choice ${choiceIndex + 1}`}
                            data-attr={`canvas-question-${questionIndex}-choice-${choiceIndex}`}
                        />
                        {isOpenChoice ? <span aria-hidden>:</span> : null}
                    </span>
                </div>
                {isOpenChoice ? (
                    <input
                        type="text"
                        placeholder="Respondent types their own answer…"
                        readOnly
                        aria-hidden
                        tabIndex={-1}
                    />
                ) : null}
            </label>
            <button
                type="button"
                className="HostedSurveyCanvasChoice__delete"
                aria-label={`Delete choice ${choiceIndex + 1}`}
                title={canDelete ? 'Delete choice' : 'A choice question needs at least one option'}
                disabled={!canDelete}
                onClick={() => onChoiceDelete(choiceIndex)}
            >
                <IconTrash />
            </button>
        </div>
    )
}

function RatingCanvas({
    question,
    onLowerBoundChange,
    onUpperBoundChange,
}: {
    question: RatingSurveyQuestion
    onLowerBoundChange: (value: string) => void
    onUpperBoundChange: (value: string) => void
}): JSX.Element {
    const scale = question.scale
    const length = scale === 10 ? 11 : scale
    return (
        <div className="rating-section">
            <div className={question.display === 'emoji' ? 'rating-options-emoji' : 'rating-options-number'}>
                {Array.from({ length }, (_, idx) => {
                    const value = scale === 10 ? idx : idx + 1
                    return (
                        <button
                            key={value}
                            type="button"
                            className={question.display === 'emoji' ? 'ratings-emoji' : 'ratings-number'}
                            tabIndex={-1}
                            aria-hidden
                        >
                            {question.display === 'emoji'
                                ? RATING_EMOJI_PREVIEW[idx] || RATING_EMOJI_PREVIEW[3]
                                : value}
                        </button>
                    )
                })}
            </div>
            <div className="rating-text">
                <InlineEditable
                    value={question.lowerBoundLabel || ''}
                    onChange={onLowerBoundChange}
                    placeholder="Low end label"
                    ariaLabel="Lower bound label"
                />
                <InlineEditable
                    value={question.upperBoundLabel || ''}
                    onChange={onUpperBoundChange}
                    placeholder="High end label"
                    ariaLabel="Upper bound label"
                />
            </div>
        </div>
    )
}

function ConfirmationCanvas({ survey }: { survey: Survey | NewSurvey }): JSX.Element {
    const { setSurveyValue } = useActions(surveyLogic)
    const appearance = survey.appearance ?? {}

    const updateAppearance = (patch: Partial<NonNullable<(Survey | NewSurvey)['appearance']>>): void => {
        setSurveyValue('appearance', { ...survey.appearance, ...patch })
    }

    return (
        <div className="thank-you-message">
            <InlineEditable
                as="h1"
                className="thank-you-message-header"
                value={appearance.thankYouMessageHeader || ''}
                onChange={(value) => updateAppearance({ thankYouMessageHeader: value })}
                placeholder="Thank you!"
                ariaLabel="Thank you header"
            />
            {appearance.thankYouMessageDescriptionContentType === 'html' && appearance.thankYouMessageDescription ? (
                // HTML descriptions keep their rendered form; v1 doesn't inline-edit raw HTML.
                <div
                    className="thank-you-message-body"
                    dangerouslySetInnerHTML={{ __html: sanitizeHTML(appearance.thankYouMessageDescription) }}
                />
            ) : (
                <InlineEditable
                    as="p"
                    className="thank-you-message-body"
                    value={appearance.thankYouMessageDescription || ''}
                    onChange={(value) => updateAppearance({ thankYouMessageDescription: value })}
                    placeholder="Add a closing message (optional)"
                    ariaLabel="Thank you description"
                    multiline
                />
            )}
            {appearance.thankYouMessageCloseButtonText !== undefined ? (
                <div className="bottom-section">
                    <InlineEditable
                        value={appearance.thankYouMessageCloseButtonText || ''}
                        onChange={(value) => updateAppearance({ thankYouMessageCloseButtonText: value })}
                        placeholder="Close"
                        ariaLabel="Close button label"
                        className="form-submit"
                    />
                </div>
            ) : null}
        </div>
    )
}
