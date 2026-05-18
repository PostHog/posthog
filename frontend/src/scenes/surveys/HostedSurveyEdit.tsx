import '../../../public/surveys/hosted-survey.css'

import { DndContext, DragEndEvent } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { getNextSurveyStep } from 'posthog-js/dist/surveys-preview'
import { useMemo, useState, type CSSProperties } from 'react'

import { IconChevronDown, IconExternal, IconGitBranch, IconPhone, IconTrash, IconWarning } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonCollapse,
    LemonDialog,
    LemonDropdown,
    LemonInput,
    LemonSegmentedButton,
    LemonSwitch,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconMonitor, SortableDragIcon } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Customization } from 'scenes/surveys/survey-appearance/SurveyCustomization'
import { SurveyTranslations } from 'scenes/surveys/SurveyTranslations'
import { sanitizeSurveyAppearance, validateSurveyAppearance } from 'scenes/surveys/utils'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import {
    RatingSurveyQuestion,
    Survey,
    SurveyQuestion,
    SurveyQuestionBranchingType,
    SurveyQuestionType,
    SurveyType,
} from '~/types'

import { SurveyBranchingFlowModal } from './branching-flow/SurveyBranchingFlowModal'
import { defaultSurveyAppearance, defaultSurveyFieldValues, NewSurvey, SurveyQuestionLabel } from './constants'
import { CopySurveyLink } from './CopySurveyLink'
import { HTMLEditor } from './SurveyAppearanceUtils'
import { SurveyEditQuestionGroup } from './SurveyEditQuestionRow'
import { surveyLogic } from './surveyLogic'
import { SurveyResponsesCollection } from './SurveyResponsesCollection'
import { getSurveyWithTranslatedContent } from './surveyTranslationUtils'
import { sanitizeHTML } from './utils'
import { AddQuestionButton } from './wizard/AddQuestionButton'

function getHostedSurveyUrl(surveyId: string): string {
    const url = new URL(window.location.origin)
    url.pathname = `/external_surveys/${surveyId}`
    return url.toString()
}

function moveQuestion(questions: SurveyQuestion[], from: number, to: number): SurveyQuestion[] {
    const nextQuestions = [...questions]
    const [question] = nextQuestions.splice(from, 1)
    nextQuestions.splice(to, 0, question)
    return nextQuestions.map((q) => ({ ...q }))
}

function getHostedPreviewAppearance(survey: Survey | NewSurvey): NonNullable<(Survey | NewSurvey)['appearance']> {
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

function getPreviewProgressValue(survey: Survey | NewSurvey, previewPageIndex: number): number {
    if (previewPageIndex >= survey.questions.length) {
        return 100
    }

    if (survey.questions.length === 0) {
        return 0
    }

    return Math.round(((previewPageIndex + 1) / survey.questions.length) * 100)
}

interface HostedPreviewCSSProperties extends CSSProperties {
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

type PreviewResponse = string | string[] | number | null

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

function hasPreviewResponse(question: SurveyQuestion, response: PreviewResponse): boolean {
    if (question.type === SurveyQuestionType.Link) {
        return true
    }
    if (question.optional) {
        return true
    }
    if (Array.isArray(response)) {
        return response.length > 0
    }
    if (typeof response === 'string') {
        return response.trim().length > 0
    }
    return response !== null
}

function SurveyPreviewDescription({ question }: { question: SurveyQuestion }): JSX.Element | null {
    if (!question.description) {
        return null
    }

    if (question.descriptionContentType === 'html') {
        return (
            <div
                className="survey-question-description"
                dangerouslySetInnerHTML={{ __html: sanitizeHTML(question.description) }}
            />
        )
    }

    return <p className="survey-question-description">{question.description}</p>
}

function HostedSurveyQuestionPreview({
    question,
    response,
    onResponseChange,
    onSubmit,
}: {
    question: SurveyQuestion
    response: PreviewResponse
    onResponseChange: (response: PreviewResponse) => void
    onSubmit: (response: PreviewResponse) => void
}): JSX.Element {
    const buttonText = question.buttonText || (question.type === SurveyQuestionType.Link ? 'Continue' : 'Submit')
    const canSubmit = hasPreviewResponse(question, response)

    const submitButton = (
        <div className="bottom-section">
            <button
                type="button"
                className="form-submit"
                disabled={!canSubmit}
                onClick={() => {
                    if (canSubmit) {
                        onSubmit(response)
                    }
                }}
            >
                {buttonText}
            </button>
            <span className="survey-keyhint">
                <span className="survey-keyhint-row">
                    <kbd className="survey-kbd">{'\u21B5'}</kbd>
                    <span className="survey-keyhint-label">submit</span>
                </span>
            </span>
        </div>
    )

    return (
        <form className="survey-form" name="surveyForm">
            <div className="survey-box" data-question-index="0">
                <div className="question-container">
                    <div>
                        <h1 className="survey-question">{question.question || 'Untitled question'}</h1>
                        <SurveyPreviewDescription question={question} />
                    </div>
                    {question.type === SurveyQuestionType.Open ? (
                        <textarea
                            value={typeof response === 'string' ? response : ''}
                            placeholder="Start typing..."
                            onChange={(event) => onResponseChange(event.target.value)}
                        />
                    ) : null}
                    {question.type === SurveyQuestionType.Link ? (
                        <Link to={question.link ?? '#'} target="_blank">
                            {question.link || 'https://posthog.com'}
                        </Link>
                    ) : null}
                    {(question.type === SurveyQuestionType.SingleChoice ||
                        question.type === SurveyQuestionType.MultipleChoice) && (
                        <fieldset>
                            <legend className="sr-only">{question.question}</legend>
                            <div className="multiple-choice-options">
                                {question.choices.map((choice, choiceIndex) => {
                                    const values = Array.isArray(response) ? response : []
                                    const checked =
                                        question.type === SurveyQuestionType.SingleChoice
                                            ? response === choice
                                            : values.includes(choice)

                                    return (
                                        <label key={choiceIndex}>
                                            <span className="response-choice">
                                                <input
                                                    type={
                                                        question.type === SurveyQuestionType.SingleChoice
                                                            ? 'radio'
                                                            : 'checkbox'
                                                    }
                                                    checked={checked}
                                                    onChange={() => {
                                                        if (question.type === SurveyQuestionType.SingleChoice) {
                                                            onResponseChange(choice)
                                                            if (question.skipSubmitButton) {
                                                                onSubmit(choice)
                                                            }
                                                            return
                                                        }

                                                        const nextValues = checked
                                                            ? values.filter((value) => value !== choice)
                                                            : [...values, choice]
                                                        onResponseChange(nextValues)
                                                    }}
                                                />
                                                {choice}
                                            </span>
                                        </label>
                                    )
                                })}
                            </div>
                        </fieldset>
                    )}
                    {question.type === SurveyQuestionType.Rating ? (
                        <div className="rating-section">
                            <div
                                className={
                                    question.display === 'emoji' ? 'rating-options-emoji' : 'rating-options-number'
                                }
                            >
                                {Array.from(
                                    {
                                        length: question.scale === 10 ? 11 : question.scale,
                                    },
                                    (_, index) => {
                                        const value = question.scale === 10 ? index : index + 1
                                        const isActive = response === value
                                        return (
                                            <button
                                                key={value}
                                                type="button"
                                                className={
                                                    question.display === 'emoji'
                                                        ? `ratings-emoji ${isActive ? 'rating-active' : ''}`
                                                        : `ratings-number ${isActive ? 'rating-active' : ''}`
                                                }
                                                onClick={() => {
                                                    onResponseChange(value)
                                                    if (question.skipSubmitButton) {
                                                        onSubmit(value)
                                                    }
                                                }}
                                            >
                                                {question.display === 'emoji'
                                                    ? RATING_EMOJI_PREVIEW[index] || RATING_EMOJI_PREVIEW[3]
                                                    : value}
                                            </button>
                                        )
                                    }
                                )}
                            </div>
                            <div className="rating-text">
                                <span>{question.lowerBoundLabel}</span>
                                <span>{question.upperBoundLabel}</span>
                            </div>
                        </div>
                    ) : null}
                    {submitButton}
                </div>
            </div>
        </form>
    )
}

function HostedSurveyConfirmationPreview({ survey }: { survey: Survey | NewSurvey }): JSX.Element {
    const appearance = survey.appearance ?? {}
    const closeButtonText = appearance.thankYouMessageCloseButtonText

    return (
        <div className="thank-you-message">
            <h1 className="thank-you-message-header">{appearance.thankYouMessageHeader || 'Thank you!'}</h1>
            {appearance.thankYouMessageDescription ? (
                appearance.thankYouMessageDescriptionContentType === 'html' ? (
                    <div
                        className="thank-you-message-body"
                        dangerouslySetInnerHTML={{ __html: sanitizeHTML(appearance.thankYouMessageDescription) }}
                    />
                ) : (
                    <p className="thank-you-message-body">{appearance.thankYouMessageDescription}</p>
                )
            ) : null}
            {closeButtonText ? (
                <div className="bottom-section">
                    <button type="button" className="form-submit" disabled>
                        {closeButtonText}
                    </button>
                </div>
            ) : null}
        </div>
    )
}

function HostedSurveyPreview({
    survey,
    previewPageIndex,
    onPreviewPageChange,
}: {
    survey: Survey | NewSurvey
    previewPageIndex: number
    onPreviewPageChange: (pageIndex: number) => void
}): JSX.Element {
    const [viewport, setViewport] = useState<'desktop' | 'mobile'>('desktop')
    const [previewResponses, setPreviewResponses] = useState<Record<number, PreviewResponse>>({})
    const totalPages = survey.questions.length + (survey.appearance?.displayThankYouMessage ? 1 : 0)
    const hostedAppearance = getHostedPreviewAppearance(survey)
    const previewProgress = getPreviewProgressValue(survey, previewPageIndex)
    const cardBg = hostedAppearance.inputBackground || hostedAppearance.backgroundColor || '#ffffff'
    const primaryText =
        hostedAppearance.textColor || hostedAppearance.inputTextColor || getContrastingTextColor(cardBg) || '#111111'
    const submitButtonColor = hostedAppearance.submitButtonColor || '#111111'
    const ratingButtonColor = hostedAppearance.ratingButtonColor || cardBg
    const ratingActiveColor = hostedAppearance.ratingButtonActiveColor || submitButtonColor
    const previewStyles: HostedPreviewCSSProperties = {
        '--ph-survey-progress-value': `${previewProgress}%`,
        '--ph-survey-page-background': hostedAppearance.backgroundColor || '#ffffff',
        '--ph-survey-page-text': primaryText,
        '--ph-survey-page-text-subtle': hostedAppearance.textSubtleColor || '#6b6b6b',
        '--ph-survey-page-progress-bar': submitButtonColor,
        '--ph-survey-page-progress-track': 'rgba(17, 17, 17, 0.08)',
        '--ph-survey-pill-background': 'rgba(255, 255, 255, 0.7)',
        '--ph-survey-card-shadow': '0 1px 2px rgba(17, 17, 17, 0.04), 0 2px 8px rgba(17, 17, 17, 0.04)',
        '--ph-survey-input-background': cardBg,
        '--ph-survey-background-color': cardBg,
        '--ph-survey-border-color': hostedAppearance.borderColor || 'rgba(17, 17, 17, 0.10)',
        '--ph-survey-border-radius': hostedAppearance.borderRadius || '10px',
        '--ph-survey-text-primary-color': primaryText,
        '--ph-survey-input-text-color': primaryText,
        '--ph-survey-text-subtle-color': hostedAppearance.textSubtleColor || '#6b6b6b',
        '--ph-survey-submit-button-color': submitButtonColor,
        '--ph-survey-submit-button-text-color':
            hostedAppearance.submitButtonTextColor || getContrastingTextColor(submitButtonColor) || '#ffffff',
        '--ph-survey-rating-bg-color': ratingButtonColor,
        '--ph-survey-rating-text-color': getContrastingTextColor(ratingButtonColor) || primaryText,
        '--ph-survey-rating-active-bg-color': ratingActiveColor,
        '--ph-survey-rating-active-text-color': getContrastingTextColor(ratingActiveColor) || '#ffffff',
    }
    const previewQuestion = survey.questions[previewPageIndex]
    const isConfirmationPreview = previewPageIndex >= survey.questions.length

    const submitPreviewResponse = (response: PreviewResponse): void => {
        const nextStep = getNextSurveyStep(survey, previewPageIndex, response)
        if (nextStep === SurveyQuestionBranchingType.End && !survey.appearance?.displayThankYouMessage) {
            return
        }
        onPreviewPageChange(nextStep === SurveyQuestionBranchingType.End ? survey.questions.length : nextStep)
    }

    return (
        <aside className="xl:sticky xl:top-16 flex min-w-0 flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                    <h3 className="mb-0 text-sm font-semibold uppercase tracking-wide text-secondary">Preview</h3>
                    <p className="mb-0 text-xs text-secondary">
                        {totalPages > 0 ? `Step ${Math.min(previewPageIndex + 1, totalPages)} of ${totalPages}` : null}
                    </p>
                </div>
                <LemonSegmentedButton
                    size="small"
                    value={viewport}
                    onChange={setViewport}
                    options={[
                        { label: <IconMonitor />, value: 'desktop', tooltip: 'Desktop preview' },
                        { label: <IconPhone />, value: 'mobile', tooltip: 'Mobile preview' },
                    ]}
                />
            </div>
            <div className="HostedSurveyPublicPreview rounded border bg-surface-primary p-3 shadow-sm">
                <div
                    className={
                        viewport === 'mobile'
                            ? 'PostHogHostedSurvey HostedSurveyPreviewFrame HostedSurveyPreviewFrame--mobile'
                            : 'PostHogHostedSurvey HostedSurveyPreviewFrame'
                    }
                    style={previewStyles}
                >
                    <div className="survey-progress-wrap">
                        <div
                            className="survey-progress-track"
                            role="progressbar"
                            aria-label="Survey progress"
                            aria-valuemin={0}
                            aria-valuemax={100}
                            aria-valuenow={previewProgress}
                        >
                            <span className="survey-progress-bar" />
                        </div>
                    </div>
                    <div className="survey-stage">
                        <div className="posthog-survey-container">
                            {isConfirmationPreview || !previewQuestion ? (
                                <HostedSurveyConfirmationPreview survey={survey} />
                            ) : (
                                <HostedSurveyQuestionPreview
                                    question={previewQuestion}
                                    response={previewResponses[previewPageIndex] ?? null}
                                    onResponseChange={(response) =>
                                        setPreviewResponses((responses) => ({
                                            ...responses,
                                            [previewPageIndex]: response,
                                        }))
                                    }
                                    onSubmit={submitPreviewResponse}
                                />
                            )}
                        </div>
                    </div>
                    {!hostedAppearance.whiteLabel ? <div className="footer-branding">Survey by PostHog</div> : null}
                </div>
            </div>
            <div className="flex items-center justify-between gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconChevronDown className="rotate-90" />}
                    disabledReason={previewPageIndex <= 0 ? 'Already at the first step' : undefined}
                    onClick={() => onPreviewPageChange(Math.max(previewPageIndex - 1, 0))}
                >
                    Previous
                </LemonButton>
                <LemonButton
                    type="secondary"
                    size="small"
                    sideIcon={<IconChevronDown className="-rotate-90" />}
                    disabledReason={
                        previewPageIndex >= totalPages - 1 || totalPages === 0 ? 'Already at the last step' : undefined
                    }
                    onClick={() => onPreviewPageChange(Math.min(previewPageIndex + 1, totalPages - 1))}
                >
                    Next
                </LemonButton>
            </div>
        </aside>
    )
}

function HostedSurveyQuestionRail({
    id,
    survey,
    hostedSurveyUrl,
    selectedPageIndex,
    onSelectPage,
    onAddQuestion,
    onAddConfirmation,
    onMoveQuestion,
    onDeleteQuestion,
    onIframeEmbeddingChange,
}: {
    id: string
    survey: Survey | NewSurvey
    hostedSurveyUrl: string | null
    selectedPageIndex: number
    onSelectPage: (pageIndex: number) => void
    onAddQuestion: (type: SurveyQuestionType) => void
    onAddConfirmation: () => void
    onMoveQuestion: (from: number, to: number) => void
    onDeleteQuestion: (index: number) => void
    onIframeEmbeddingChange: (checked: boolean) => void
}): JSX.Element {
    const sortedItemIds = survey.questions.map((_, index) => index.toString())

    const handleDragEnd = ({ active, over }: DragEndEvent): void => {
        if (!over || active.id === over.id) {
            return
        }

        const oldIndex = sortedItemIds.indexOf(active.id.toString())
        const newIndex = sortedItemIds.indexOf(over.id.toString())
        if (oldIndex < 0 || newIndex < 0) {
            return
        }

        onMoveQuestion(oldIndex, newIndex)
    }

    return (
        <nav className="flex min-w-0 flex-col gap-3 rounded border bg-surface-primary p-3">
            <div className="flex items-center justify-between gap-2 border-b pb-2">
                <div>
                    <h3 className="mb-0 text-sm font-semibold uppercase tracking-wide text-secondary">Flow</h3>
                    <p className="mb-0 text-xs text-muted">{survey.questions.length} question steps</p>
                </div>
            </div>
            <div className="flex flex-col gap-2">
                <DndContext onDragEnd={handleDragEnd}>
                    <SortableContext
                        disabled={survey.questions.length <= 1}
                        items={sortedItemIds}
                        strategy={verticalListSortingStrategy}
                    >
                        <div className="flex flex-col gap-1">
                            {survey.questions.map((question, index) => (
                                <HostedSurveyQuestionRailItem
                                    key={`${question.id ?? 'question'}-${index}`}
                                    id={index.toString()}
                                    question={question}
                                    index={index}
                                    isSelected={selectedPageIndex === index}
                                    canReorder={survey.questions.length > 1}
                                    canDelete={survey.questions.length > 1}
                                    onSelect={() => onSelectPage(index)}
                                    onDelete={() => onDeleteQuestion(index)}
                                />
                            ))}
                        </div>
                    </SortableContext>
                </DndContext>
                {survey.appearance?.displayThankYouMessage ? (
                    <button
                        type="button"
                        className={`min-h-11 rounded border px-3 py-2 text-left text-sm transition-colors ${
                            selectedPageIndex === survey.questions.length
                                ? 'border-primary bg-primary-highlight text-primary'
                                : 'bg-bg-light hover:bg-fill-highlight-50'
                        }`}
                        onClick={() => onSelectPage(survey.questions.length)}
                    >
                        <span className="block font-medium">Confirmation</span>
                        <span className="block text-xs text-secondary">End screen</span>
                    </button>
                ) : (
                    <LemonButton type="secondary" size="small" onClick={onAddConfirmation} className="mt-1" fullWidth>
                        Add confirmation
                    </LemonButton>
                )}
                <AddQuestionButton onAdd={onAddQuestion} />
            </div>
            <HostedSurveySharingPanel
                id={id}
                hostedSurveyUrl={hostedSurveyUrl}
                enableIframeEmbedding={!!survey.enable_iframe_embedding}
                onIframeEmbeddingChange={onIframeEmbeddingChange}
            />
        </nav>
    )
}

function HostedSurveyQuestionRailItem({
    id,
    question,
    index,
    isSelected,
    canReorder,
    canDelete,
    onSelect,
    onDelete,
}: {
    id: string
    question: SurveyQuestion
    index: number
    isSelected: boolean
    canReorder: boolean
    canDelete: boolean
    onSelect: () => void
    onDelete: () => void
}): JSX.Element {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id,
        animateLayoutChanges: () => false,
    })

    return (
        <div
            ref={setNodeRef}
            {...attributes}
            className={`group flex min-h-[3.75rem] items-center gap-2 rounded border px-2 py-2 transition-colors ${
                isSelected
                    ? 'border-primary bg-primary-highlight text-primary'
                    : 'bg-bg-light hover:bg-fill-highlight-50'
            } ${isDragging ? 'opacity-50' : ''}`}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                transform: CSS.Translate.toString(transform),
                transition,
            }}
        >
            {canReorder ? (
                <span
                    className="shrink-0 cursor-grab text-muted hover:text-primary active:cursor-grabbing"
                    {...listeners}
                    aria-label={`Reorder question ${index + 1}`}
                >
                    <SortableDragIcon />
                </span>
            ) : null}
            <button type="button" className="flex min-w-0 flex-1 flex-col text-left" onClick={onSelect}>
                <span className="min-w-0 truncate text-sm font-medium">{question.question || 'Untitled question'}</span>
                <span className="mt-0.5 flex items-center gap-1 text-xs text-secondary">
                    <span>{index + 1}</span>
                    <span aria-hidden="true">/</span>
                    <span>{SurveyQuestionLabel[question.type]}</span>
                </span>
            </button>
            {canDelete ? (
                <LemonButton
                    icon={<IconTrash />}
                    size="xsmall"
                    status="danger"
                    onClick={onDelete}
                    aria-label="Delete question"
                />
            ) : null}
        </div>
    )
}

function HostedSurveySharingPanel({
    id,
    hostedSurveyUrl,
    enableIframeEmbedding,
    onIframeEmbeddingChange,
}: {
    id: string
    hostedSurveyUrl: string | null
    enableIframeEmbedding: boolean
    onIframeEmbeddingChange: (checked: boolean) => void
}): JSX.Element {
    return (
        <section className="mt-1 border-t pt-3">
            <div className="mb-2">
                <h3 className="mb-0 text-sm font-semibold uppercase tracking-wide text-secondary">Sharing</h3>
                <p className="mb-0 text-xs text-muted">URL options for hosted surveys</p>
            </div>
            <div className="flex flex-col gap-2">
                {hostedSurveyUrl ? (
                    <CopySurveyLink
                        surveyId={id}
                        enableIframeEmbedding={enableIframeEmbedding}
                        className="flex-wrap [&_.LemonButton]:flex-1 [&_.LemonButton]:justify-center"
                    />
                ) : (
                    <div className="rounded border bg-bg-light p-2 text-xs text-secondary">
                        Save this survey before copying a public URL or embed code.
                    </div>
                )}
                <Tooltip title="Enable this to embed the survey in tools like Framer, Webflow, or other website builders that use iframes.">
                    <div className="flex min-h-10 items-center">
                        <LemonSwitch
                            checked={enableIframeEmbedding}
                            onChange={onIframeEmbeddingChange}
                            label="Allow iframe embedding"
                        />
                    </div>
                </Tooltip>
                <div className="flex items-center justify-between gap-2 py-1 text-xs text-secondary">
                    <span className="min-w-0">Identify, prefill, and translate with URL parameters.</span>
                    <HostedSurveyUrlParamsDropdown />
                </div>
            </div>
        </section>
    )
}

function HostedSurveyUrlParamsDropdown(): JSX.Element {
    return (
        <LemonDropdown
            placement="bottom-start"
            overlay={
                <div className="max-w-80 p-3 text-xs text-secondary">
                    <p className="mb-2 font-semibold text-default">Useful URL params</p>
                    <dl className="mb-0 flex flex-col gap-2">
                        <div>
                            <dt className="font-medium text-default">
                                <code className="rounded bg-surface-tertiary px-1">distinct_id</code>
                            </dt>
                            <dd className="mb-0">Identify the respondent.</dd>
                        </div>
                        <div>
                            <dt className="font-medium text-default">
                                <code className="rounded bg-surface-tertiary px-1">q1</code>,{' '}
                                <code className="rounded bg-surface-tertiary px-1">q2</code>
                            </dt>
                            <dd className="mb-0">Prefill answers by question order. Complete prefills auto-submit.</dd>
                        </div>
                        <div>
                            <dt className="font-medium text-default">
                                <code className="rounded bg-surface-tertiary px-1">display_language</code>
                            </dt>
                            <dd className="mb-0">Force a translated survey language.</dd>
                        </div>
                        <div>
                            <dt className="font-medium text-default">Custom params</dt>
                            <dd className="mb-0">Extra params are captured as survey response event properties.</dd>
                        </div>
                    </dl>
                    <Link
                        to="https://posthog.com/docs/surveys/creating-surveys#identifying-respondents-on-hosted-surveys"
                        target="_blank"
                        className="mt-2 inline-block"
                    >
                        Hosted survey docs
                    </Link>
                </div>
            }
        >
            <LemonButton type="tertiary" size="xsmall" sideIcon={<IconChevronDown />}>
                URL params
            </LemonButton>
        </LemonDropdown>
    )
}

function HostedSurveyConfirmationEditor(): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)

    return (
        <div className="flex flex-col gap-3">
            <LemonField.Pure label="Thank you header">
                <LemonInput
                    value={survey.appearance?.thankYouMessageHeader ?? ''}
                    onChange={(thankYouMessageHeader) =>
                        setSurveyValue('appearance', {
                            ...survey.appearance,
                            thankYouMessageHeader,
                        })
                    }
                    placeholder="Thank you for your feedback!"
                />
            </LemonField.Pure>
            <LemonField.Pure label="Thank you description">
                <HTMLEditor
                    value={survey.appearance?.thankYouMessageDescription ?? ''}
                    onChange={(thankYouMessageDescription) =>
                        setSurveyValue('appearance', {
                            ...survey.appearance,
                            thankYouMessageDescription,
                        })
                    }
                    activeTab={survey.appearance?.thankYouMessageDescriptionContentType ?? 'text'}
                    onTabChange={(key) =>
                        setSurveyValue('appearance', {
                            ...survey.appearance,
                            thankYouMessageDescriptionContentType: key === 'html' ? 'html' : 'text',
                        })
                    }
                    textPlaceholder="We really appreciate it."
                />
            </LemonField.Pure>
            <LemonField.Pure label="Button text">
                <LemonInput
                    value={survey.appearance?.thankYouMessageCloseButtonText ?? ''}
                    onChange={(thankYouMessageCloseButtonText) =>
                        setSurveyValue('appearance', {
                            ...survey.appearance,
                            thankYouMessageCloseButtonText,
                        })
                    }
                    placeholder="Close"
                />
            </LemonField.Pure>
        </div>
    )
}

function HostedSurveyEditorHeader({
    id,
    survey,
    surveyLoading,
    hostedSurveyUrl,
    onNameChange,
    onDescriptionChange,
    onCancel,
    onConvertToInApp,
}: {
    id: string
    survey: Survey | NewSurvey
    surveyLoading: boolean
    hostedSurveyUrl: string | null
    onNameChange: (name: string) => void
    onDescriptionChange: (description: string) => void
    onCancel: () => void
    onConvertToInApp: () => void
}): JSX.Element {
    return (
        <header className="rounded border bg-surface-primary p-3">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                <div className="flex min-w-0 flex-1 flex-col gap-2">
                    <div className="flex items-center gap-2">
                        <span className="rounded bg-accent-highlight px-2 py-0.5 text-xs font-semibold text-accent">
                            Hosted survey
                        </span>
                        <span className="text-xs text-secondary">One question at a time</span>
                    </div>
                    <div className="grid min-w-0 gap-2 lg:grid-cols-[minmax(260px,0.55fr)_minmax(220px,0.45fr)]">
                        <LemonInput
                            value={survey.name}
                            onChange={onNameChange}
                            placeholder="Untitled hosted survey"
                            className="font-semibold"
                        />
                        <LemonInput
                            value={survey.description ?? ''}
                            onChange={onDescriptionChange}
                            placeholder="Internal description"
                        />
                    </div>
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-2">
                    <LemonButton type="secondary" size="small" onClick={onConvertToInApp}>
                        Convert to in-app
                    </LemonButton>
                    {hostedSurveyUrl ? (
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconExternal />}
                            to={hostedSurveyUrl}
                            targetBlank
                        >
                            Open
                        </LemonButton>
                    ) : null}
                    <LemonButton
                        data-attr="cancel-survey"
                        type="secondary"
                        loading={surveyLoading}
                        onClick={onCancel}
                        size="small"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        data-attr="save-survey"
                        htmlType="submit"
                        loading={surveyLoading}
                        form="survey"
                        size="small"
                    >
                        {id === 'new' ? 'Save as draft' : 'Save'}
                    </LemonButton>
                </div>
            </div>
        </header>
    )
}

export function HostedSurveyEdit({ id }: { id: string }): JSX.Element {
    const { survey, selectedPageIndex, hasBranchingLogic, surveyErrors, surveyLoading, editingLanguage } =
        useValues(surveyLogic)
    const {
        deleteBranchingLogic,
        editingSurvey,
        loadSurvey,
        setEditingLanguage,
        setSelectedPageIndex,
        setSurveyManualErrors,
        setSurveyValue,
    } = useActions(surveyLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const [showFlowModal, setShowFlowModal] = useState(false)

    const surveyTranslationsEnabled = !!featureFlags[FEATURE_FLAGS.SURVEYS_TRANSLATIONS]
    const maxPageIndex = Math.max(survey.questions.length + (survey.appearance?.displayThankYouMessage ? 1 : 0) - 1, 0)
    const activePageIndex = Math.min(selectedPageIndex ?? 0, maxPageIndex)
    const activeQuestion = survey.questions[activePageIndex]
    const isConfirmationSelected =
        !!survey.appearance?.displayThankYouMessage && activePageIndex === survey.questions.length
    const previewSurvey = useMemo(
        () => getSurveyWithTranslatedContent(survey, surveyTranslationsEnabled ? editingLanguage : null),
        [editingLanguage, survey, surveyTranslationsEnabled]
    )
    const hostedSurveyUrl = id === 'new' ? null : getHostedSurveyUrl(id)

    const runAfterBranchingConfirmation = (action: () => void, description: JSX.Element): void => {
        if (!hasBranchingLogic) {
            action()
            return
        }

        LemonDialog.open({
            title: 'Your survey has active branching logic',
            description,
            primaryButton: {
                children: 'Continue',
                status: 'danger',
                onClick: () => {
                    deleteBranchingLogic()
                    action()
                },
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    const addQuestion = (type: SurveyQuestionType): void => {
        const newQuestion = { ...defaultSurveyFieldValues[type].questions[0] } as SurveyQuestion
        const existingLanguages = Object.keys(survey.translations || {})

        if (existingLanguages.length > 0) {
            newQuestion.translations = {}
            existingLanguages.forEach((language) => {
                newQuestion.translations = {
                    ...newQuestion.translations,
                    [language]: {
                        question: newQuestion.question || '',
                        description: newQuestion.description || '',
                        buttonText: newQuestion.buttonText || '',
                    },
                }
            })
        }

        setSurveyValue('questions', [...survey.questions, newQuestion])
        setSelectedPageIndex(survey.questions.length)
    }

    const moveSurveyQuestion = (from: number, to: number): void => {
        runAfterBranchingConfirmation(
            () => {
                setSurveyValue('questions', moveQuestion(survey.questions, from, to))
                setSelectedPageIndex(to)
            },
            <p className="py-2">Rearranging questions will remove your branching logic. Continue?</p>
        )
    }

    const deleteSurveyQuestion = (index: number): void => {
        runAfterBranchingConfirmation(
            () => {
                setSurveyValue(
                    'questions',
                    survey.questions.filter((_, questionIndex) => questionIndex !== index)
                )
                setSelectedPageIndex(Math.max(index - 1, 0))
            },
            <p className="py-2">Deleting this question will remove your branching logic. Continue?</p>
        )
    }

    const handleCancelClick = (): void => {
        editingSurvey(false)
        if (id === 'new') {
            router.actions.push(urls.surveys())
        } else {
            loadSurvey()
        }
    }

    const convertToInAppSurvey = (): void => {
        LemonDialog.open({
            title: 'Convert to in-app survey?',
            description: (
                <p className="py-2">
                    This keeps the questions and style, then switches the editor back to the in-app survey setup where
                    display conditions and placement are available.
                </p>
            ),
            primaryButton: {
                children: 'Convert',
                onClick: () => {
                    setSurveyValue('type', SurveyType.Popover)
                    setSurveyValue('enable_iframe_embedding', false)
                    setSelectedPageIndex(0)
                },
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    return (
        <SceneContent>
            <div className="flex flex-col gap-4">
                <HostedSurveyEditorHeader
                    id={id}
                    survey={survey}
                    surveyLoading={surveyLoading}
                    hostedSurveyUrl={hostedSurveyUrl}
                    onNameChange={(name) => setSurveyValue('name', name)}
                    onDescriptionChange={(description) => setSurveyValue('description', description)}
                    onCancel={handleCancelClick}
                    onConvertToInApp={convertToInAppSurvey}
                />
                <div className="grid min-h-[640px] grid-cols-1 gap-4 xl:grid-cols-[300px_minmax(420px,0.9fr)_minmax(520px,1.1fr)]">
                    <HostedSurveyQuestionRail
                        id={id}
                        survey={survey}
                        hostedSurveyUrl={hostedSurveyUrl}
                        selectedPageIndex={activePageIndex}
                        onSelectPage={setSelectedPageIndex}
                        onAddQuestion={addQuestion}
                        onAddConfirmation={() => {
                            setSurveyValue('appearance', {
                                ...survey.appearance,
                                displayThankYouMessage: true,
                            })
                            setSelectedPageIndex(survey.questions.length)
                        }}
                        onMoveQuestion={moveSurveyQuestion}
                        onDeleteQuestion={deleteSurveyQuestion}
                        onIframeEmbeddingChange={(checked) => setSurveyValue('enable_iframe_embedding', checked)}
                    />
                    <main className="flex min-w-0 flex-col gap-4">
                        <section className="rounded border bg-surface-primary p-5">
                            <div className="mb-5 flex flex-wrap items-start justify-between gap-2 border-b pb-4">
                                <div>
                                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-secondary">
                                        {isConfirmationSelected ? 'End screen' : `Step ${activePageIndex + 1}`}
                                    </p>
                                    <h2 className="mb-0 text-base font-semibold">
                                        {isConfirmationSelected
                                            ? 'Confirmation message'
                                            : activeQuestion?.question || 'Untitled question'}
                                    </h2>
                                    <p className="mb-0 text-xs text-secondary">
                                        {isConfirmationSelected
                                            ? 'Shown after the final answer.'
                                            : activeQuestion
                                              ? SurveyQuestionLabel[activeQuestion.type]
                                              : 'Question'}
                                    </p>
                                </div>
                                {isConfirmationSelected ? (
                                    <LemonButton
                                        type="secondary"
                                        status="danger"
                                        size="small"
                                        icon={<IconTrash />}
                                        onClick={() => {
                                            setSurveyValue('appearance', {
                                                ...survey.appearance,
                                                displayThankYouMessage: false,
                                            })
                                            setSelectedPageIndex(Math.max(survey.questions.length - 1, 0))
                                        }}
                                    >
                                        Remove
                                    </LemonButton>
                                ) : null}
                            </div>
                            {isConfirmationSelected ? (
                                <HostedSurveyConfirmationEditor />
                            ) : (
                                <SurveyEditQuestionGroup
                                    index={activePageIndex}
                                    question={
                                        survey.questions[activePageIndex] as SurveyQuestion | RatingSurveyQuestion
                                    }
                                />
                            )}
                        </section>
                        {surveyTranslationsEnabled ? (
                            <section className="rounded border bg-surface-primary p-5">
                                <div className="mb-4 border-b pb-3">
                                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-secondary">
                                        Languages
                                    </p>
                                    <h2 className="mb-0 text-base font-semibold">Translations</h2>
                                    <p className="mb-0 text-xs text-secondary">
                                        Localize the hosted survey without changing the default flow.
                                    </p>
                                </div>
                                <div className="flex flex-col gap-3">
                                    {editingLanguage ? (
                                        <div className="rounded border border-warning bg-warning-highlight p-3 text-sm">
                                            Editing translated survey content. Question order and settings stay in the
                                            default language.
                                        </div>
                                    ) : null}
                                    <SurveyTranslations />
                                    {editingLanguage ? (
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={() => setEditingLanguage(null)}
                                            className="w-max"
                                        >
                                            Edit default language
                                        </LemonButton>
                                    ) : null}
                                </div>
                            </section>
                        ) : null}
                        <LemonCollapse
                            className="bg-surface-primary rounded border"
                            panels={[
                                {
                                    key: 'appearance',
                                    header: 'Style',
                                    content: (
                                        <LemonField name="appearance" label="">
                                            {({ onChange }) => (
                                                <Customization
                                                    survey={survey}
                                                    hasBranchingLogic={hasBranchingLogic}
                                                    deleteBranchingLogic={deleteBranchingLogic}
                                                    hasRatingButtons={survey.questions.some(
                                                        (question) => question.type === SurveyQuestionType.Rating
                                                    )}
                                                    hasPlaceholderText={survey.questions.some(
                                                        (question) => question.type === SurveyQuestionType.Open
                                                    )}
                                                    onAppearanceChange={(appearance) => {
                                                        const newAppearance = sanitizeSurveyAppearance({
                                                            ...survey.appearance,
                                                            ...appearance,
                                                        })
                                                        onChange(newAppearance)
                                                        if (newAppearance) {
                                                            setSurveyManualErrors(
                                                                validateSurveyAppearance(
                                                                    newAppearance,
                                                                    true,
                                                                    SurveyType.ExternalSurvey
                                                                )
                                                            )
                                                        }
                                                    }}
                                                    validationErrors={surveyErrors?.appearance}
                                                />
                                            )}
                                        </LemonField>
                                    ),
                                },
                                {
                                    key: 'collection',
                                    header: 'Collection',
                                    content: (
                                        <div className="flex flex-col gap-4">
                                            <LemonField.Pure label={<h3 className="mb-0">Completion limit</h3>}>
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <LemonCheckbox
                                                        checked={!!survey.responses_limit}
                                                        onChange={(checked) =>
                                                            setSurveyValue('responses_limit', checked ? 100 : null)
                                                        }
                                                        label="Stop collecting after"
                                                    />
                                                    <LemonInput
                                                        type="number"
                                                        min={1}
                                                        size="small"
                                                        value={survey.responses_limit || NaN}
                                                        onChange={(value) => {
                                                            setSurveyValue(
                                                                'responses_limit',
                                                                value && value > 0 ? value : null
                                                            )
                                                        }}
                                                        className="w-20"
                                                    />
                                                    responses
                                                </div>
                                            </LemonField.Pure>
                                            <SurveyResponsesCollection />
                                        </div>
                                    ),
                                },
                            ]}
                        />
                        {hasBranchingLogic ? (
                            <LemonButton
                                data-attr="preview-survey-branching"
                                type="secondary"
                                className="w-max"
                                icon={<IconGitBranch />}
                                onClick={() => setShowFlowModal(true)}
                            >
                                Preview branching flow
                            </LemonButton>
                        ) : null}
                    </main>
                    <HostedSurveyPreview
                        survey={previewSurvey}
                        previewPageIndex={activePageIndex}
                        onPreviewPageChange={setSelectedPageIndex}
                    />
                </div>
                {id === 'new' ? (
                    <div className="flex items-center gap-2 rounded border bg-accent-highlight p-3 text-sm">
                        <IconWarning className="text-warning" />
                        Save this hosted survey before sharing or embedding it.
                    </div>
                ) : null}
            </div>
            <SurveyBranchingFlowModal survey={survey} isOpen={showFlowModal} onClose={() => setShowFlowModal(false)} />
        </SceneContent>
    )
}
