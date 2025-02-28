import DOMPurify from 'dompurify'
import { SURVEY_RESPONSE_PROPERTY } from 'scenes/surveys/constants'
import { SurveyRatingResults } from 'scenes/surveys/surveyLogic'

import { EventPropertyFilter, Survey, SurveyAppearance } from '~/types'

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

        // Extract question index from the filter key (assuming format like "$survey_response_X")
        const questionIndexMatch = filter.key.match(/\$survey_response_(\d+)/)
        if (!questionIndexMatch) {
            continue // Skip if we can't determine the question index
        }

        const questionIndex = parseInt(questionIndexMatch[1])
        const questionId = survey.questions[questionIndex]?.id

        // Get both key formats
        const { indexBasedKey, idBasedKey } = getResponseFieldWithId(questionIndex, questionId)

        // Create the condition for this filter
        let condition = ''

        // Handle different operators
        switch (filter.operator) {
            case 'exact':
                if (Array.isArray(filter.value)) {
                    // Handle array values with IN operator
                    const valueList = filter.value.map((v) => `'${v}'`).join(', ')
                    condition = `(properties['${indexBasedKey}'] IN (${valueList})`
                    if (idBasedKey) {
                        condition += ` OR properties['${idBasedKey}'] IN (${valueList})`
                    }
                } else {
                    // Handle single value
                    condition = `(properties['${indexBasedKey}'] = '${filter.value}'`
                    if (idBasedKey) {
                        condition += ` OR properties['${idBasedKey}'] = '${filter.value}'`
                    }
                }
                condition += ')'
                break
            case 'is_not':
                if (Array.isArray(filter.value)) {
                    // Handle array values with NOT IN operator
                    const valueList = filter.value.map((v) => `'${v}'`).join(', ')
                    condition = `(properties['${indexBasedKey}'] NOT IN (${valueList})`
                    if (idBasedKey) {
                        condition += ` OR properties['${idBasedKey}'] NOT IN (${valueList})`
                    }
                } else {
                    // Handle single value
                    condition = `(properties['${indexBasedKey}'] != '${filter.value}'`
                    if (idBasedKey) {
                        condition += ` OR properties['${idBasedKey}'] != '${filter.value}'`
                    }
                }
                condition += ')'
                break
            case 'icontains':
                // For ILIKE, we typically don't use arrays, but handle it just in case
                const searchValue = Array.isArray(filter.value) ? filter.value[0] : filter.value
                condition = `(properties['${indexBasedKey}'] ILIKE '%${searchValue}%'`
                if (idBasedKey) {
                    condition += ` OR properties['${idBasedKey}'] ILIKE '%${searchValue}%'`
                }
                condition += ')'
                break
            case 'regex':
                // Use match() function for regex
                const regexPattern = Array.isArray(filter.value) ? filter.value[0] : filter.value
                condition = `(match(properties['${indexBasedKey}'], '${regexPattern}')`
                if (idBasedKey) {
                    condition += ` OR match(properties['${idBasedKey}'], '${regexPattern}')`
                }
                condition += ')'
                break
            case 'not_regex':
                // Use NOT match() function for negative regex
                const notRegexPattern = Array.isArray(filter.value) ? filter.value[0] : filter.value
                condition = `(NOT match(properties['${indexBasedKey}'], '${notRegexPattern}')`
                if (idBasedKey) {
                    condition += ` OR NOT match(properties['${idBasedKey}'], '${notRegexPattern}')`
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

    console.log({ filterExpression })

    return hasValidFilter ? `AND ${filterExpression}` : ''
}
