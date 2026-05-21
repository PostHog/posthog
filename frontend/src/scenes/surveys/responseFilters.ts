import { getSurveyIdBasedResponseKey } from 'scenes/surveys/utils'

import {
    EventPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    SurveyEventProperties,
    SurveyQuestion,
    SurveyQuestionType,
} from '~/types'

export type RatingFilterMode = 'gte' | 'lte' | 'eq' | 'between'
export type OpenTextFilterMode = 'any' | 'contains' | 'not_contains'
export type SingleChoiceFilterMode = 'is_any_of' | 'is_none_of'
export type MultipleChoiceFilterMode = 'includes_any' | 'includes_none'

export type SurveyResponseFilter =
    | {
          questionId: string
          type: SurveyQuestionType.Rating
          mode: RatingFilterMode
          value: number | null
          upperValue?: number | null
      }
    | {
          questionId: string
          type: SurveyQuestionType.Open
          mode: OpenTextFilterMode
          value: string
      }
    | {
          questionId: string
          type: SurveyQuestionType.SingleChoice
          mode: SingleChoiceFilterMode
          value: string[]
      }
    | {
          questionId: string
          type: SurveyQuestionType.MultipleChoice
          mode: MultipleChoiceFilterMode
          value: string[]
      }

const RATING_OPERATOR_BY_MODE: Record<Exclude<RatingFilterMode, 'between'>, PropertyOperator> = {
    gte: PropertyOperator.GreaterThanOrEqual,
    lte: PropertyOperator.LessThanOrEqual,
    eq: PropertyOperator.Exact,
}

const OPEN_TEXT_OPERATOR_BY_MODE: Record<Exclude<OpenTextFilterMode, 'any'>, PropertyOperator> = {
    contains: PropertyOperator.IContains,
    not_contains: PropertyOperator.NotIContains,
}

const SINGLE_CHOICE_OPERATOR_BY_MODE: Record<SingleChoiceFilterMode, PropertyOperator> = {
    is_any_of: PropertyOperator.Exact,
    is_none_of: PropertyOperator.IsNot,
}

const MULTIPLE_CHOICE_OPERATOR_BY_MODE: Record<MultipleChoiceFilterMode, PropertyOperator> = {
    includes_any: PropertyOperator.IContains,
    includes_none: PropertyOperator.NotIContains,
}

export function isSurveyResponsePropertyKey(key: string | null | undefined): boolean {
    return typeof key === 'string' && key.startsWith(`${SurveyEventProperties.SURVEY_RESPONSE}_`)
}

export function isResponseFilterValid(filter: SurveyResponseFilter): boolean {
    switch (filter.type) {
        case SurveyQuestionType.Rating: {
            if (filter.mode === 'between') {
                return (
                    typeof filter.value === 'number' &&
                    typeof filter.upperValue === 'number' &&
                    filter.value <= filter.upperValue
                )
            }
            return typeof filter.value === 'number'
        }
        case SurveyQuestionType.Open:
            return filter.mode === 'any' ? true : filter.value.trim().length > 0
        case SurveyQuestionType.SingleChoice:
        case SurveyQuestionType.MultipleChoice:
            return filter.value.length > 0
    }
}

export function defaultResponseFilterForQuestion(question: SurveyQuestion): SurveyResponseFilter | null {
    if (!question.id) {
        return null
    }
    switch (question.type) {
        case SurveyQuestionType.Rating:
            return { questionId: question.id, type: question.type, mode: 'lte', value: null }
        case SurveyQuestionType.Open:
            return { questionId: question.id, type: question.type, mode: 'any', value: '' }
        case SurveyQuestionType.SingleChoice:
            return { questionId: question.id, type: question.type, mode: 'is_any_of', value: [] }
        case SurveyQuestionType.MultipleChoice:
            return { questionId: question.id, type: question.type, mode: 'includes_any', value: [] }
        case SurveyQuestionType.Link:
            return null
    }
}

function buildEventPropertyFilters(filter: SurveyResponseFilter): EventPropertyFilter[] {
    const key = getSurveyIdBasedResponseKey(filter.questionId)
    const base = { key, type: PropertyFilterType.Event } as const

    switch (filter.type) {
        case SurveyQuestionType.Rating: {
            if (filter.value === null || filter.value === undefined) {
                return []
            }
            if (filter.mode === 'between') {
                if (filter.upperValue === null || filter.upperValue === undefined) {
                    return []
                }
                return [
                    { ...base, operator: PropertyOperator.GreaterThanOrEqual, value: filter.value },
                    { ...base, operator: PropertyOperator.LessThanOrEqual, value: filter.upperValue },
                ]
            }
            return [{ ...base, operator: RATING_OPERATOR_BY_MODE[filter.mode], value: filter.value }]
        }
        case SurveyQuestionType.Open: {
            if (filter.mode === 'any') {
                return [{ ...base, operator: PropertyOperator.IsSet, value: PropertyOperator.IsSet }]
            }
            const trimmed = filter.value.trim()
            if (!trimmed) {
                return []
            }
            return [{ ...base, operator: OPEN_TEXT_OPERATOR_BY_MODE[filter.mode], value: trimmed }]
        }
        case SurveyQuestionType.SingleChoice: {
            if (filter.value.length === 0) {
                return []
            }
            return [{ ...base, operator: SINGLE_CHOICE_OPERATOR_BY_MODE[filter.mode], value: filter.value }]
        }
        case SurveyQuestionType.MultipleChoice: {
            if (filter.value.length === 0) {
                return []
            }
            return [{ ...base, operator: MULTIPLE_CHOICE_OPERATOR_BY_MODE[filter.mode], value: filter.value }]
        }
    }
}

export function buildResponseFilterProperties(filters: SurveyResponseFilter[]): EventPropertyFilter[] {
    return filters.filter(isResponseFilterValid).flatMap(buildEventPropertyFilters)
}

function findQuestionByResponseKey(
    key: string | null | undefined,
    questions: SurveyQuestion[]
): SurveyQuestion | undefined {
    if (typeof key !== 'string') {
        return undefined
    }
    return questions.find((question) => question.id && getSurveyIdBasedResponseKey(question.id) === key)
}

function toFiniteNumber(value: unknown): number | null {
    if (typeof value === 'number' && Number.isFinite(value)) {
        return value
    }
    if (typeof value === 'string' && value.trim() !== '') {
        const parsed = Number(value)
        return Number.isFinite(parsed) ? parsed : null
    }
    return null
}

function toStringArray(value: unknown): string[] {
    if (Array.isArray(value)) {
        return value.filter((v): v is string => typeof v === 'string' && v.length > 0)
    }
    if (typeof value === 'string' && value.length > 0) {
        return [value]
    }
    return []
}

export function parseResponseFiltersFromProperties(
    properties: EventPropertyFilter[] | undefined | null,
    questions: SurveyQuestion[]
): SurveyResponseFilter[] {
    if (!properties || properties.length === 0) {
        return []
    }

    const parsed: SurveyResponseFilter[] = []
    const byQuestionId: Record<string, SurveyResponseFilter> = {}

    for (const property of properties) {
        if (property.type !== PropertyFilterType.Event || !isSurveyResponsePropertyKey(property.key)) {
            continue
        }
        const question = findQuestionByResponseKey(property.key, questions)
        if (!question?.id) {
            continue
        }

        switch (question.type) {
            case SurveyQuestionType.Rating: {
                const numeric = toFiniteNumber(property.value)
                if (numeric === null) {
                    continue
                }
                const existing = byQuestionId[question.id]
                if (existing && existing.type === SurveyQuestionType.Rating) {
                    if (
                        property.operator === PropertyOperator.LessThanOrEqual &&
                        existing.mode === 'gte' &&
                        existing.value !== null &&
                        existing.value !== undefined
                    ) {
                        existing.mode = 'between'
                        existing.upperValue = numeric
                        continue
                    }
                    if (
                        property.operator === PropertyOperator.GreaterThanOrEqual &&
                        existing.mode === 'lte' &&
                        existing.value !== null &&
                        existing.value !== undefined
                    ) {
                        existing.mode = 'between'
                        existing.upperValue = existing.value
                        existing.value = numeric
                        continue
                    }
                }
                let mode: RatingFilterMode = 'eq'
                if (property.operator === PropertyOperator.GreaterThanOrEqual) {
                    mode = 'gte'
                } else if (property.operator === PropertyOperator.LessThanOrEqual) {
                    mode = 'lte'
                }
                const entry: SurveyResponseFilter = {
                    questionId: question.id,
                    type: SurveyQuestionType.Rating,
                    mode,
                    value: numeric,
                }
                byQuestionId[question.id] = entry
                parsed.push(entry)
                break
            }
            case SurveyQuestionType.Open: {
                if (property.operator === PropertyOperator.IsSet) {
                    const entry: SurveyResponseFilter = {
                        questionId: question.id,
                        type: SurveyQuestionType.Open,
                        mode: 'any',
                        value: '',
                    }
                    byQuestionId[question.id] = entry
                    parsed.push(entry)
                    break
                }
                if (
                    property.operator === PropertyOperator.IContains ||
                    property.operator === PropertyOperator.NotIContains
                ) {
                    const text = typeof property.value === 'string' ? property.value : ''
                    const entry: SurveyResponseFilter = {
                        questionId: question.id,
                        type: SurveyQuestionType.Open,
                        mode: property.operator === PropertyOperator.IContains ? 'contains' : 'not_contains',
                        value: text,
                    }
                    byQuestionId[question.id] = entry
                    parsed.push(entry)
                }
                break
            }
            case SurveyQuestionType.SingleChoice: {
                const values = toStringArray(property.value)
                if (values.length === 0) {
                    continue
                }
                const entry: SurveyResponseFilter = {
                    questionId: question.id,
                    type: SurveyQuestionType.SingleChoice,
                    mode: property.operator === PropertyOperator.IsNot ? 'is_none_of' : 'is_any_of',
                    value: values,
                }
                byQuestionId[question.id] = entry
                parsed.push(entry)
                break
            }
            case SurveyQuestionType.MultipleChoice: {
                const values = toStringArray(property.value)
                if (values.length === 0) {
                    continue
                }
                const entry: SurveyResponseFilter = {
                    questionId: question.id,
                    type: SurveyQuestionType.MultipleChoice,
                    mode: property.operator === PropertyOperator.NotIContains ? 'includes_none' : 'includes_any',
                    value: values,
                }
                byQuestionId[question.id] = entry
                parsed.push(entry)
                break
            }
        }
    }

    return parsed
}

export function stripResponseFiltersFromProperties(
    properties: EventPropertyFilter[] | undefined | null
): EventPropertyFilter[] {
    if (!properties) {
        return []
    }
    return properties.filter((property) => !isSurveyResponsePropertyKey(property.key))
}
