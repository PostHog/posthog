import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonInputSelect, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { SurveyResponseFilter, defaultResponseFilterForQuestion } from 'scenes/surveys/responseFilters'

import {
    BasicSurveyQuestion,
    MultipleSurveyQuestion,
    RatingSurveyQuestion,
    SurveyQuestion,
    SurveyQuestionType,
} from '~/types'

const RATING_MODE_OPTIONS = [
    { value: 'lte' as const, label: 'is at most' },
    { value: 'gte' as const, label: 'is at least' },
    { value: 'eq' as const, label: 'equals' },
    { value: 'between' as const, label: 'is between' },
]

const OPEN_TEXT_MODE_OPTIONS = [
    { value: 'any' as const, label: 'has any response' },
    { value: 'contains' as const, label: 'contains' },
    { value: 'not_contains' as const, label: 'does not contain' },
]

const SINGLE_CHOICE_MODE_OPTIONS = [
    { value: 'is_any_of' as const, label: 'is any of' },
    { value: 'is_none_of' as const, label: 'is none of' },
]

const MULTIPLE_CHOICE_MODE_OPTIONS = [
    { value: 'includes_any' as const, label: 'includes any of' },
    { value: 'includes_none' as const, label: 'includes none of' },
]

function getQuestionLabel(question: SurveyQuestion, index: number): string {
    return question.question?.trim() || `Question ${index + 1}`
}

function isFilterableQuestion(
    question: SurveyQuestion
): question is BasicSurveyQuestion | RatingSurveyQuestion | MultipleSurveyQuestion {
    return question.type !== SurveyQuestionType.Link && !!question.id
}

function RatingFilterControls({
    question,
    filter,
    onChange,
}: {
    question: RatingSurveyQuestion
    filter: Extract<SurveyResponseFilter, { type: SurveyQuestionType.Rating }>
    onChange: (next: SurveyResponseFilter) => void
}): JSX.Element {
    const minValue = question.scale === 10 ? 0 : 1
    const maxValue = question.scale
    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonSelect
                size="small"
                value={filter.mode}
                onChange={(mode) => onChange({ ...filter, mode })}
                options={RATING_MODE_OPTIONS}
            />
            <LemonInput
                type="number"
                size="small"
                min={minValue}
                max={maxValue}
                value={filter.value ?? undefined}
                onChange={(value) => onChange({ ...filter, value: typeof value === 'number' ? value : null })}
                className="w-20"
            />
            {filter.mode === 'between' ? (
                <>
                    <span className="text-xs text-muted">and</span>
                    <LemonInput
                        type="number"
                        size="small"
                        min={minValue}
                        max={maxValue}
                        value={filter.upperValue ?? undefined}
                        onChange={(value) =>
                            onChange({ ...filter, upperValue: typeof value === 'number' ? value : null })
                        }
                        className="w-20"
                    />
                </>
            ) : null}
            <span className="text-xs text-muted">
                (scale {minValue}–{maxValue})
            </span>
        </div>
    )
}

function OpenTextFilterControls({
    filter,
    onChange,
}: {
    filter: Extract<SurveyResponseFilter, { type: SurveyQuestionType.Open }>
    onChange: (next: SurveyResponseFilter) => void
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonSelect
                size="small"
                value={filter.mode}
                onChange={(mode) => {
                    if (mode === 'any') {
                        onChange({ ...filter, mode, value: '' })
                    } else {
                        onChange({ ...filter, mode })
                    }
                }}
                options={OPEN_TEXT_MODE_OPTIONS}
            />
            {filter.mode !== 'any' ? (
                <LemonInput
                    size="small"
                    value={filter.value}
                    onChange={(value) => onChange({ ...filter, value })}
                    placeholder="text to match"
                    className="min-w-48"
                />
            ) : null}
        </div>
    )
}

function ChoiceFilterControls<
    T extends Extract<
        SurveyResponseFilter,
        { type: SurveyQuestionType.SingleChoice | SurveyQuestionType.MultipleChoice }
    >,
>({
    question,
    filter,
    options,
    onChange,
}: {
    question: MultipleSurveyQuestion
    filter: T
    options: { value: T['mode']; label: string }[]
    onChange: (next: SurveyResponseFilter) => void
}): JSX.Element {
    const choiceOptions = question.choices.map((choice) => ({ key: choice, label: choice, value: choice }))
    return (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <LemonSelect
                size="small"
                value={filter.mode}
                onChange={(mode) => onChange({ ...filter, mode } as SurveyResponseFilter)}
                options={options}
            />
            <div className="flex-1 min-w-48">
                <LemonInputSelect
                    mode="multiple"
                    size="small"
                    placeholder="Select choices"
                    options={choiceOptions}
                    value={filter.value}
                    onChange={(value) => onChange({ ...filter, value } as SurveyResponseFilter)}
                />
            </div>
        </div>
    )
}

function FilterRow({
    question,
    questionIndex,
    filter,
    onChange,
    onRemove,
}: {
    question: SurveyQuestion
    questionIndex: number
    filter: SurveyResponseFilter
    onChange: (next: SurveyResponseFilter) => void
    onRemove: () => void
}): JSX.Element | null {
    let controls: JSX.Element | null = null
    if (filter.type === SurveyQuestionType.Rating && question.type === SurveyQuestionType.Rating) {
        controls = <RatingFilterControls question={question} filter={filter} onChange={onChange} />
    } else if (filter.type === SurveyQuestionType.Open && question.type === SurveyQuestionType.Open) {
        controls = <OpenTextFilterControls filter={filter} onChange={onChange} />
    } else if (filter.type === SurveyQuestionType.SingleChoice && question.type === SurveyQuestionType.SingleChoice) {
        controls = (
            <ChoiceFilterControls
                question={question}
                filter={filter}
                options={SINGLE_CHOICE_MODE_OPTIONS}
                onChange={onChange}
            />
        )
    } else if (
        filter.type === SurveyQuestionType.MultipleChoice &&
        question.type === SurveyQuestionType.MultipleChoice
    ) {
        controls = (
            <ChoiceFilterControls
                question={question}
                filter={filter}
                options={MULTIPLE_CHOICE_MODE_OPTIONS}
                onChange={onChange}
            />
        )
    }

    if (!controls) {
        return null
    }

    return (
        <div className="rounded border border-border bg-bg-light px-3 py-2 space-y-2">
            <div className="flex items-start justify-between gap-2">
                <div className="text-xs font-medium text-default break-words">
                    {getQuestionLabel(question, questionIndex)}
                </div>
                <Tooltip title="Remove filter">
                    <LemonButton size="xsmall" type="tertiary" icon={<IconTrash />} onClick={onRemove} />
                </Tooltip>
            </div>
            {controls}
        </div>
    )
}

export function SurveyResponseFilters({
    questions,
    filters,
    onChange,
}: {
    questions: SurveyQuestion[]
    filters: SurveyResponseFilter[]
    onChange: (next: SurveyResponseFilter[]) => void
}): JSX.Element | null {
    const filterableQuestions = questions.filter(isFilterableQuestion)
    if (filterableQuestions.length === 0) {
        return null
    }

    const questionById = new Map<string, { question: SurveyQuestion; index: number }>()
    questions.forEach((question, index) => {
        if (question.id) {
            questionById.set(question.id, { question, index })
        }
    })

    const usedQuestionIds = new Set(filters.map((filter) => filter.questionId))
    const availableQuestions = filterableQuestions.filter(
        (question) => question.id && !usedQuestionIds.has(question.id)
    )

    const addFilterFor = (question: SurveyQuestion): void => {
        const next = defaultResponseFilterForQuestion(question)
        if (!next) {
            return
        }
        onChange([...filters, next])
    }

    const updateFilter = (index: number, next: SurveyResponseFilter): void => {
        const updated = [...filters]
        updated[index] = next
        onChange(updated)
    }

    const removeFilter = (index: number): void => {
        onChange(filters.filter((_, i) => i !== index))
    }

    return (
        <div className="space-y-3">
            <div className="border-t border-border" />
            <div className="space-y-1">
                <div className="text-sm font-medium text-default">Only notify when…</div>
                <div className="text-xs text-muted">
                    Quiet down noisy notifications by filtering on response content. Filters apply to completed
                    responses only and are combined with AND.
                </div>
            </div>

            {filters.length > 0 ? (
                <div className="space-y-2">
                    {filters.map((filter, index) => {
                        const entry = questionById.get(filter.questionId)
                        if (!entry) {
                            return null
                        }
                        return (
                            <FilterRow
                                key={`${filter.questionId}-${index}`}
                                question={entry.question}
                                questionIndex={entry.index}
                                filter={filter}
                                onChange={(next) => updateFilter(index, next)}
                                onRemove={() => removeFilter(index)}
                            />
                        )
                    })}
                </div>
            ) : null}

            {availableQuestions.length > 0 ? (
                <LemonMenu
                    items={availableQuestions.map((question) => {
                        const index = questionById.get(question.id!)?.index ?? 0
                        return {
                            label: getQuestionLabel(question, index),
                            onClick: () => addFilterFor(question),
                        }
                    })}
                >
                    <LemonButton size="small" type="secondary" icon={<IconPlus />}>
                        Add response filter
                    </LemonButton>
                </LemonMenu>
            ) : (
                <div className="text-xs text-muted">All eligible questions already have a filter.</div>
            )}
        </div>
    )
}
