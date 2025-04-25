import DOMPurify from 'dompurify'
import { SURVEY_RESPONSE_PROPERTY } from 'scenes/surveys/constants'
import { SurveyRatingResults } from 'scenes/surveys/surveyLogic'

import { EventPropertyFilter, Survey, SurveyAppearance, SurveyDisplayConditions } from '~/types'

const sanitizeConfig = { ADD_ATTR: ['target'] }

export function sanitizeHTML(html: string): string {
    return DOMPurify.sanitize(html, sanitizeConfig)
}

export function sanitizeColor(color: string | undefined): string | undefined {
    if (!color) {
        return undefined
    }

    // test if the color is valid by adding a # to the beginning of the string
    if (!validateColor(`#${color}`, 'color')) {
        return `#${color}`
    }

    return color
}

export function validateColor(color: string | undefined, fieldName: string): string | undefined {
    if (!color) {
        return undefined
    }
    // Test if the color value is valid using CSS.supports
    const isValidColor = CSS.supports('color', color)
    return !isValidColor ? `Invalid color value for ${fieldName}. Please use a valid CSS color.` : undefined
}

export function getSurveyResponseKey(questionIndex: number): string {
    return questionIndex === 0 ? SURVEY_RESPONSE_PROPERTY : `${SURVEY_RESPONSE_PROPERTY}_${questionIndex}`
}

export function getSurveyIdBasedResponseKey(questionId: string): string {
    return `${SURVEY_RESPONSE_PROPERTY}_${questionId}`
}

// Helper function to generate the response field keys with proper typing
export const getResponseFieldWithId = (
    questionIndex: number,
    questionId?: string
): { indexBasedKey: string; idBasedKey: string | undefined } => {
    return {
        indexBasedKey: getSurveyResponseKey(questionIndex),
        idBasedKey: questionId ? getSurveyIdBasedResponseKey(questionId) : undefined,
    }
}

export function sanitizeSurveyDisplayConditions(
    displayConditions: SurveyDisplayConditions | null
): SurveyDisplayConditions | null {
    if (!displayConditions) {
        return null
    }

    return {
        ...displayConditions,
        url: displayConditions.url.trim(),
        selector: displayConditions.selector?.trim(),
    }
}

export function sanitizeSurveyAppearance(appearance: SurveyAppearance | null): SurveyAppearance | null {
    if (!appearance) {
        return null
    }

    return {
        ...appearance,
        backgroundColor: sanitizeColor(appearance.backgroundColor),
        borderColor: sanitizeColor(appearance.borderColor),
        ratingButtonActiveColor: sanitizeColor(appearance.ratingButtonActiveColor),
        ratingButtonColor: sanitizeColor(appearance.ratingButtonColor),
        submitButtonColor: sanitizeColor(appearance.submitButtonColor),
        submitButtonTextColor: sanitizeColor(appearance.submitButtonTextColor),
    }
}

export type NPSBreakdown = {
    total: number
    promoters: number
    passives: number
    detractors: number
}

export function calculateNpsBreakdown(surveyRatingResults: SurveyRatingResults[number]): NPSBreakdown | null {
    // Validate input structure
    if (!surveyRatingResults.data || surveyRatingResults.data.length !== 11) {
        return null
    }

    if (surveyRatingResults.total === 0) {
        return { total: 0, promoters: 0, passives: 0, detractors: 0 }
    }

    const PROMOTER_MIN = 9
    const PASSIVE_MIN = 7

    const promoters = surveyRatingResults.data.slice(PROMOTER_MIN, 11).reduce((a, b) => a + b, 0)
    const passives = surveyRatingResults.data.slice(PASSIVE_MIN, PROMOTER_MIN).reduce((a, b) => a + b, 0)
    const detractors = surveyRatingResults.data.slice(0, PASSIVE_MIN).reduce((a, b) => a + b, 0)
    return { total: surveyRatingResults.total, promoters, passives, detractors }
}

export function calculateNpsScore(npsBreakdown: NPSBreakdown): number {
    if (npsBreakdown.total === 0) {
        return 0
    }
    return ((npsBreakdown.promoters - npsBreakdown.detractors) / npsBreakdown.total) * 100
}

// Helper to escape special characters in SQL strings
function escapeSqlString(value: string): string {
    return value.replace(/['\\]/g, '\\$&')
}

/**
 * Creates a HogQL expression for survey answer filters that handles both index-based and ID-based property keys
 * using OR logic between the alternative formats for each question.
 *
 * @param filters - The answer filters to convert to HogQL expressions
 * @param survey - The survey object (needed to access question IDs)
 * @returns A HogQL expression string that can be used in queries. If there are no filters, it returns an empty string.
 *
 * TODO: Consider leveraging the backend query builder instead of duplicating this logic in the frontend.
 * ClickHouse has powerful functions like match(), multiIf(), etc. that could be used more effectively.
 */
export function createAnswerFilterHogQLExpression(filters: EventPropertyFilter[], survey: Survey): string {
    if (!filters || !filters.length) {
        return ''
    }

    // Build the filter expression as a string
    let filterExpression = ''
    let hasValidFilter = false

    // Process each filter
    for (const filter of filters) {
        // Skip filters with empty or undefined values
        if (filter.value === undefined || filter.value === null || filter.value === '') {
            continue
        }

        // Skip empty arrays
        if (Array.isArray(filter.value) && filter.value.length === 0) {
            continue
        }

        // Skip ILIKE filters with empty search patterns
        if (
            filter.operator === 'icontains' &&
            (filter.value === '%' ||
                filter.value === '%%' ||
                (typeof filter.value === 'string' && filter.value.trim() === ''))
        ) {
            continue
        }

        // split the string '$survey_response_' and take the last part, as that's the question id
        const questionId = filter.key.split(`${SURVEY_RESPONSE_PROPERTY}_`).at(-1)
        if (!questionId || !survey.questions.find((question) => question.id === questionId)) {
            continue
        }
        const questionIndex = survey.questions.findIndex((question) => question.id === questionId)

        // Create the condition for this filter
        let condition = ''
        let escapedValue: string
        let valueList: string

        // Handle different operators
        switch (filter.operator) {
            case 'exact':
            case 'is_not':
                if (Array.isArray(filter.value)) {
                    valueList = filter.value.map((v) => `'${escapeSqlString(String(v))}'`).join(', ')
                    condition = `(getSurveyResponse(${questionIndex}, '${questionId}') ${
                        filter.operator === 'is_not' ? 'NOT IN' : 'IN'
                    } (${valueList}))`
                } else {
                    escapedValue = escapeSqlString(String(filter.value))
                    condition = `(getSurveyResponse(${questionIndex}, '${questionId}') ${
                        filter.operator === 'is_not' ? '!=' : '='
                    } '${escapedValue}')`
                }
                break
            case 'icontains':
                escapedValue = escapeSqlString(String(filter.value))
                condition = `(getSurveyResponse(${questionIndex}, '${questionId}') ILIKE '%${escapedValue}%')`
                break
            case 'not_icontains':
                escapedValue = escapeSqlString(String(filter.value))
                condition = `(NOT getSurveyResponse(${questionIndex}, '${questionId}') ILIKE '%${escapedValue}%')`
                break
            case 'regex':
                escapedValue = escapeSqlString(String(filter.value))
                condition = `(match(getSurveyResponse(${questionIndex}, '${questionId}'), '${escapedValue}'))`
                break
            case 'not_regex':
                escapedValue = escapeSqlString(String(filter.value))
                condition = `(NOT match(getSurveyResponse(${questionIndex}, '${questionId}'), '${escapedValue}'))`
                break
            // Add more operators as needed
            default:
                continue // Skip unsupported operators
        }

        // Add this condition to the overall expression
        if (condition) {
            if (hasValidFilter) {
                filterExpression += ' AND '
            }
            filterExpression += condition
            hasValidFilter = true
        }
    }

    return hasValidFilter ? `AND ${filterExpression}` : ''
}

export function isSurveyRunning(survey: Survey): boolean {
    return !!(survey.start_date && !survey.end_date)
}
