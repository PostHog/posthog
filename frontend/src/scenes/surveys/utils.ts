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

// Helper function to generate the response field keys with proper typing
export const getResponseFieldWithId = (
    questionIndex: number,
    questionId?: string
): { indexBasedKey: string; idBasedKey: string | undefined } => {
    return {
        indexBasedKey: getSurveyResponseKey(questionIndex),
        idBasedKey: questionId ? `${SURVEY_RESPONSE_PROPERTY}_${questionId}` : undefined,
    }
}

// Helper function to generate the HogQL condition for checking survey responses in both formats
export const getResponseFieldCondition = (questionIndex: number, questionId?: string): string => {
    const ids = getResponseFieldWithId(questionIndex, questionId)

    if (!ids.idBasedKey) {
        return `JSONExtractString(properties, '${ids.indexBasedKey}')`
    }

    // For ClickHouse, we need to use coalesce to check both fields
    // This will return the first non-null value, prioritizing the ID-based format if available
    return `coalesce(
        nullIf(JSONExtractString(properties, '${ids.idBasedKey}'), ''),
        nullIf(JSONExtractString(properties, '${ids.indexBasedKey}'), '')
    )`
}

// Helper function to generate the HogQL condition for checking multiple choice survey responses in both formats
export const getMultipleChoiceResponseFieldCondition = (questionIndex: number, questionId?: string): string => {
    const ids = getResponseFieldWithId(questionIndex, questionId)

    if (!ids.idBasedKey) {
        return `JSONExtractArrayRaw(properties, '${ids.indexBasedKey}')`
    }

    // For multiple choice, we need to check if either field has a value and use that one
    return `if(
        JSONHas(properties, '${ids.idBasedKey}') AND length(JSONExtractArrayRaw(properties, '${ids.idBasedKey}')) > 0,
        JSONExtractArrayRaw(properties, '${ids.idBasedKey}'),
        JSONExtractArrayRaw(properties, '${ids.indexBasedKey}')
    )`
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
 * @returns A HogQL expression string that can be used in queries
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

        // Extract question index from the filter key (assuming format like "$survey_response_X" or "$survey_response")
        let questionIndex = 0
        if (filter.key === '$survey_response') {
            // If the key is exactly "$survey_response", it's for question index 0
            questionIndex = 0
        } else {
            const questionIndexMatch = filter.key.match(/\$survey_response_(\d+)/)
            if (!questionIndexMatch) {
                continue // Skip if we can't determine the question index
            }
            questionIndex = parseInt(questionIndexMatch[1])
        }

        // Check if question index is valid before accessing
        if (questionIndex >= survey.questions.length) {
            continue // Skip if question index is out of bounds
        }
        const questionId = survey.questions[questionIndex]?.id

        // Get both key formats
        const { indexBasedKey, idBasedKey } = getResponseFieldWithId(questionIndex, questionId)

        // Create the condition for this filter
        let condition = ''
        let escapedValue: string
        let valueList: string

        // Handle different operators
        switch (filter.operator) {
            case 'exact':
                if (Array.isArray(filter.value)) {
                    valueList = filter.value.map((v) => `'${escapeSqlString(String(v))}'`).join(', ')
                    condition = `(properties['${indexBasedKey}'] IN (${valueList})`
                    if (idBasedKey) {
                        condition += ` OR properties['${idBasedKey}'] IN (${valueList})`
                    }
                } else {
                    escapedValue = escapeSqlString(String(filter.value))
                    condition = `(properties['${indexBasedKey}'] = '${escapedValue}'`
                    if (idBasedKey) {
                        condition += ` OR properties['${idBasedKey}'] = '${escapedValue}'`
                    }
                }
                condition += ')'
                break
            case 'is_not':
                if (Array.isArray(filter.value)) {
                    valueList = filter.value.map((v) => `'${escapeSqlString(String(v))}'`).join(', ')
                    condition = `(properties['${indexBasedKey}'] NOT IN (${valueList})`
                    if (idBasedKey) {
                        condition += ` OR properties['${idBasedKey}'] NOT IN (${valueList})`
                    }
                } else {
                    escapedValue = escapeSqlString(String(filter.value))
                    condition = `(properties['${indexBasedKey}'] != '${escapedValue}'`
                    if (idBasedKey) {
                        condition += ` OR properties['${idBasedKey}'] != '${escapedValue}'`
                    }
                }
                condition += ')'
                break
            case 'icontains':
                escapedValue = escapeSqlString(String(filter.value))
                condition = `(properties['${indexBasedKey}'] ILIKE '%${escapedValue}%'`
                if (idBasedKey) {
                    condition += ` OR properties['${idBasedKey}'] ILIKE '%${escapedValue}%'`
                }
                condition += ')'
                break
            case 'regex':
                escapedValue = escapeSqlString(String(filter.value))
                condition = `(match(properties['${indexBasedKey}'], '${escapedValue}')`
                if (idBasedKey) {
                    condition += ` OR match(properties['${idBasedKey}'], '${escapedValue}')`
                }
                condition += ')'
                break
            case 'not_regex':
                escapedValue = escapeSqlString(String(filter.value))
                condition = `(NOT match(properties['${indexBasedKey}'], '${escapedValue}')`
                if (idBasedKey) {
                    condition += ` OR NOT match(properties['${idBasedKey}'], '${escapedValue}')`
                }
                condition += ')'
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
