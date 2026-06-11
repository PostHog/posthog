import { useActions, useValues } from 'kea'

import { IconPhone, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDialog, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { IconMonitor } from 'lib/lemon-ui/icons'
import { SCALE_OPTIONS, SURVEY_RATING_SCALE, SurveyQuestionLabel } from 'scenes/surveys/constants'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { isThumbQuestion } from 'scenes/surveys/utils'

import {
    type MultipleSurveyQuestion,
    type RatingSurveyQuestion,
    type SurveyQuestion,
    SurveyQuestionType,
} from '~/types'

interface HostedSurveySettingsPanelProps {
    /** Active page in the canvas — used to pick the question to render settings for. */
    activePageIndex: number
    isConfirmation: boolean
    viewport: 'desktop' | 'mobile'
    onViewportChange: (viewport: 'desktop' | 'mobile') => void
    onRemoveConfirmation: () => void
}

const QUESTION_TYPE_OPTIONS = [
    { label: SurveyQuestionLabel[SurveyQuestionType.Open], value: SurveyQuestionType.Open },
    { label: 'Link / Notification', value: SurveyQuestionType.Link },
    { label: 'Rating', value: SurveyQuestionType.Rating },
    { label: 'Single choice', value: SurveyQuestionType.SingleChoice },
    { label: 'Multiple choice', value: SurveyQuestionType.MultipleChoice },
]

/**
 * Right-side settings panel for the hosted survey canvas. Houses everything that
 * doesn't fit inline on the canvas: type switching, scale config, choice options,
 * branching, viewport toggle, optional state.
 */
export function HostedSurveySettingsPanel({
    activePageIndex,
    isConfirmation,
    viewport,
    onViewportChange,
    onRemoveConfirmation,
}: HostedSurveySettingsPanelProps): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue, setDefaultForQuestionType, resetBranchingForQuestion, setMultipleSurveyQuestion } =
        useActions(surveyLogic)

    const question = survey.questions[activePageIndex] as SurveyQuestion | undefined

    const handleQuestionTypeChange = (newType: SurveyQuestionType): void => {
        if (!question) {
            return
        }
        const isCurrentMultipleChoice =
            question.type === SurveyQuestionType.MultipleChoice || question.type === SurveyQuestionType.SingleChoice
        const isNewMultipleChoice =
            newType === SurveyQuestionType.MultipleChoice || newType === SurveyQuestionType.SingleChoice

        if (isCurrentMultipleChoice && isNewMultipleChoice) {
            setMultipleSurveyQuestion(activePageIndex, question as MultipleSurveyQuestion, newType)
            resetBranchingForQuestion(activePageIndex)
            return
        }

        const apply = (): void => {
            setDefaultForQuestionType(activePageIndex, question, newType)
            resetBranchingForQuestion(activePageIndex)
        }

        // Destructive transitions (e.g. choice → rating) lose configured choices — confirm first.
        if (isCurrentMultipleChoice && !isNewMultipleChoice) {
            LemonDialog.open({
                title: 'Changing question type',
                description: <p className="py-2">The choices you configured will be removed. Continue?</p>,
                primaryButton: { children: 'Continue', status: 'danger', onClick: apply },
                secondaryButton: { children: 'Cancel' },
            })
            return
        }

        apply()
    }

    // Per-question union typing makes a strict keyof updater painful — accept arbitrary
    // values here. Callers already constrain by question type.
    const updateQuestionField = (key: string, value: unknown): void => {
        if (!question) {
            return
        }
        const next = survey.questions.map((q, idx) => (idx === activePageIndex ? { ...q, [key]: value } : q))
        setSurveyValue('questions', next)
    }

    return (
        <aside className="flex min-w-0 flex-col gap-4 rounded border bg-surface-primary p-4">
            <SettingsSection
                title={isConfirmation ? 'End screen' : `Question ${activePageIndex + 1}`}
                subtitle={
                    isConfirmation
                        ? 'Shown after the final answer.'
                        : question
                          ? SurveyQuestionLabel[question.type]
                          : 'No question selected'
                }
                actions={
                    isConfirmation ? (
                        <LemonButton
                            type="tertiary"
                            size="small"
                            status="danger"
                            icon={<IconTrash />}
                            onClick={onRemoveConfirmation}
                            tooltip="Remove the end screen"
                        />
                    ) : null
                }
            />

            {!isConfirmation && question ? (
                <>
                    <LabelledControl label="Type">
                        <LemonSelect
                            fullWidth
                            value={question.type}
                            options={QUESTION_TYPE_OPTIONS}
                            onSelect={(value) => handleQuestionTypeChange(value)}
                            data-attr={`canvas-question-${activePageIndex}-type`}
                        />
                    </LabelledControl>

                    <LemonCheckbox
                        label="Optional"
                        checked={!!question.optional}
                        onChange={(checked) => updateQuestionField('optional', checked)}
                    />

                    {question.type === SurveyQuestionType.Rating ? (
                        <RatingSettings
                            question={question as RatingSurveyQuestion}
                            onDisplayChange={(value) => {
                                const next = survey.questions.map((q, idx) =>
                                    idx === activePageIndex
                                        ? {
                                              ...q,
                                              display: value,
                                              scale: SURVEY_RATING_SCALE.LIKERT_5_POINT,
                                          }
                                        : q
                                )
                                setSurveyValue('questions', next)
                                setSurveyValue('appearance', {
                                    ...survey.appearance,
                                    ratingButtonColor: value === 'emoji' ? '#939393' : 'white',
                                })
                                resetBranchingForQuestion(activePageIndex)
                            }}
                            onScaleChange={(value) => {
                                updateQuestionField('scale', value)
                                resetBranchingForQuestion(activePageIndex)
                            }}
                            onIsNpsChange={(checked) => updateQuestionField('isNpsQuestion', checked)}
                        />
                    ) : null}

                    {(question.type === SurveyQuestionType.SingleChoice ||
                        question.type === SurveyQuestionType.MultipleChoice) && (
                        <OpenChoiceControl
                            question={question as MultipleSurveyQuestion}
                            onAdd={() => {
                                const choices = (question as MultipleSurveyQuestion).choices || []
                                const next = survey.questions.map((q, idx) =>
                                    idx === activePageIndex
                                        ? { ...q, choices: [...choices, 'Other'], hasOpenChoice: true }
                                        : q
                                )
                                setSurveyValue('questions', next)
                            }}
                            onRemove={() => {
                                const choices = (question as MultipleSurveyQuestion).choices || []
                                // Strip the trailing open-ended option and clear the flag.
                                const next = survey.questions.map((q, idx) =>
                                    idx === activePageIndex
                                        ? { ...q, choices: choices.slice(0, -1), hasOpenChoice: false }
                                        : q
                                )
                                setSurveyValue('questions', next)
                            }}
                        />
                    )}
                </>
            ) : null}

            <div className="border-t pt-3">
                <SettingsSection title="Preview" subtitle="Switch between desktop and mobile framing." />
                <LemonSegmentedButton
                    size="small"
                    value={viewport}
                    onChange={onViewportChange}
                    options={[
                        { label: <IconMonitor />, value: 'desktop', tooltip: 'Desktop' },
                        { label: <IconPhone />, value: 'mobile', tooltip: 'Mobile' },
                    ]}
                    fullWidth
                />
            </div>
        </aside>
    )
}

function SettingsSection({
    title,
    subtitle,
    actions,
}: {
    title: string
    subtitle?: string
    actions?: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex items-start justify-between gap-2">
            <div>
                <h3 className="mb-0 text-sm font-semibold uppercase tracking-wide text-secondary">{title}</h3>
                {subtitle ? <p className="mb-0 text-xs text-muted">{subtitle}</p> : null}
            </div>
            {actions}
        </div>
    )
}

function LabelledControl({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <label className="flex flex-col gap-1 text-xs font-medium text-secondary">
            {label}
            {children}
        </label>
    )
}

function RatingSettings({
    question,
    onDisplayChange,
    onScaleChange,
    onIsNpsChange,
}: {
    question: RatingSurveyQuestion
    onDisplayChange: (display: 'number' | 'emoji') => void
    onScaleChange: (scale: number) => void
    onIsNpsChange: (checked: boolean) => void
}): JSX.Element {
    const isNpsCheckboxApplicable = question.scale === SURVEY_RATING_SCALE.NPS_10_POINT
    return (
        <>
            <LabelledControl label="Display">
                <LemonSelect
                    fullWidth
                    value={question.display}
                    options={[
                        { label: 'Number', value: 'number' },
                        { label: 'Emoji', value: 'emoji' },
                    ]}
                    onChange={(value) => onDisplayChange(value as 'number' | 'emoji')}
                />
            </LabelledControl>
            <LabelledControl label="Scale">
                <LemonSelect
                    fullWidth
                    value={question.scale}
                    options={question.display === 'emoji' ? SCALE_OPTIONS.EMOJI : SCALE_OPTIONS.NUMBER}
                    onChange={(value) => onScaleChange(value as number)}
                />
            </LabelledControl>
            {!isThumbQuestion(question) && isNpsCheckboxApplicable ? (
                <LemonCheckbox
                    label="Treat as NPS"
                    info="If checked, we'll calculate and display NPS on the survey results page."
                    checked={question.isNpsQuestion !== false}
                    onChange={onIsNpsChange}
                />
            ) : null}
        </>
    )
}

function OpenChoiceControl({
    question,
    onAdd,
    onRemove,
}: {
    question: MultipleSurveyQuestion
    onAdd: () => void
    onRemove: () => void
}): JSX.Element {
    return question.hasOpenChoice ? (
        <LemonButton type="tertiary" size="small" status="danger" icon={<IconTrash />} onClick={onRemove}>
            Remove open-ended choice
        </LemonButton>
    ) : (
        <LemonButton type="secondary" size="small" icon={<IconPlusSmall />} onClick={onAdd}>
            Add open-ended choice
        </LemonButton>
    )
}
