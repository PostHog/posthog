import DOMPurify from 'dompurify'
import { DeepPartialMap, ValidationErrorType } from 'kea-forms'
import { dayjs } from 'lib/dayjs'
import { QuestionProcessedResponses, SurveyRatingResults } from 'scenes/surveys/surveyLogic'

import {
    EventPropertyFilter,
    Survey,
    SurveyAppearance,
    SurveyDisplayConditions,
    SurveyEventName,
    SurveyEventProperties,
    SurveyQuestion,
    SurveyQuestionType,
    SurveyType,
} from '~/types'

const sanitizeConfig = { ADD_ATTR: ['target'] }

export function sanitizeHTML(html: string): string {
    return DOMPurify.sanitize(html, sanitizeConfig)
}

export function sanitizeColor(color: string | undefined): string | undefined {
    if (!color) {
        return undefined
    }

    // test if the color is valid by adding a # to the beginning of the string
    if (CSS.supports('color', `#${color}`)) {
        return `#${color}`
    }

    return color
}

export function validateCSSProperty(property: string, value: string | undefined): string | undefined {
    if (!value) {
        return undefined
    }
    const isValidCSSProperty = CSS.supports(property, value)
    return !isValidCSSProperty ? `${value} is not a valid property for ${property}.` : undefined
}

export function validateSurveyAppearance(
    appearance: SurveyAppearance,
    hasRatingQuestions: boolean,
    surveyType: SurveyType
): DeepPartialMap<SurveyAppearance, ValidationErrorType> {
    return {
        backgroundColor: validateCSSProperty('background-color', appearance.backgroundColor),
        borderColor: validateCSSProperty('border-color', appearance.borderColor),
        // Only validate rating button colors if there's a rating question
        ...(hasRatingQuestions && {
            ratingButtonActiveColor: validateCSSProperty('background-color', appearance.ratingButtonActiveColor),
            ratingButtonColor: validateCSSProperty('background-color', appearance.ratingButtonColor),
        }),
        submitButtonColor: validateCSSProperty('background-color', appearance.submitButtonColor),
        submitButtonTextColor: validateCSSProperty('color', appearance.submitButtonTextColor),
        maxWidth: validateCSSProperty('width', appearance.maxWidth),
        boxPadding: validateCSSProperty('padding', appearance.boxPadding),
        boxShadow: validateCSSProperty('box-shadow', appearance.boxShadow),
        borderRadius: validateCSSProperty('border-radius', appearance.borderRadius),
        zIndex: validateCSSProperty('z-index', appearance.zIndex),
        widgetSelector:
            surveyType === SurveyType.Widget && appearance?.widgetType === 'selector' && !appearance.widgetSelector
                ? 'Please enter a CSS selector.'
                : undefined,
    }
}

export function getSurveyResponseKey(questionIndex: number): string {
    return questionIndex === 0
        ? SurveyEventProperties.SURVEY_RESPONSE
        : `${SurveyEventProperties.SURVEY_RESPONSE}_${questionIndex}`
}

export function getSurveyIdBasedResponseKey(questionId: string): string {
    return `${SurveyEventProperties.SURVEY_RESPONSE}_${questionId}`
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
    displayConditions?: SurveyDisplayConditions | null
): SurveyDisplayConditions | null {
    if (!displayConditions) {
        return null
    }

    return {
        ...displayConditions,
        url: displayConditions.url?.trim(),
        selector: displayConditions.selector?.trim(),
    }
}

export function sanitizeSurveyAppearance(
    appearance?: SurveyAppearance | null,
    isPartialResponsesEnabled = false
): SurveyAppearance | null {
    if (!appearance) {
        return null
    }

    return {
        ...appearance,
        shuffleQuestions: isPartialResponsesEnabled ? false : appearance.shuffleQuestions,
        backgroundColor: sanitizeColor(appearance.backgroundColor),
        borderColor: sanitizeColor(appearance.borderColor),
        ratingButtonActiveColor: sanitizeColor(appearance.ratingButtonActiveColor),
        ratingButtonColor: sanitizeColor(appearance.ratingButtonColor),
        submitButtonColor: sanitizeColor(appearance.submitButtonColor),
        submitButtonTextColor: sanitizeColor(appearance.submitButtonTextColor),
        thankYouMessageHeader: sanitizeHTML(appearance.thankYouMessageHeader ?? ''),
        thankYouMessageDescription: sanitizeHTML(appearance.thankYouMessageDescription ?? ''),
    }
}

export type NPSBreakdown = {
    total: number
    promoters: number
    passives: number
    detractors: number
    score: string
}

// NPS calculation constants
const NPS_SCALE_SIZE = 11 // 0-10 scale
const NPS_PROMOTER_MIN = 9 // 9-10 are promoters
const NPS_PASSIVE_MIN = 7 // 7-8 are passives. 0-6 are detractors but we don't need a variable for that.

interface NPSRawData {
    values: number[]
    total: number
}

/**
 * Extracts raw NPS data from processed survey data
 */
function extractNPSRawData(processedData: QuestionProcessedResponses): NPSRawData | null {
    if (
        !processedData?.data ||
        processedData.type !== SurveyQuestionType.Rating ||
        !Array.isArray(processedData.data) ||
        processedData.data.length !== NPS_SCALE_SIZE
    ) {
        return null
    }

    return {
        values: processedData.data.map((item) => item.value),
        total: processedData.totalResponses,
    }
}

/**
 * Extracts raw NPS data from legacy survey rating results
 */
function extractNPSRawDataFromLegacy(surveyRatingResults: SurveyRatingResults[number]): NPSRawData | null {
    if (!surveyRatingResults?.data || surveyRatingResults.data.length !== NPS_SCALE_SIZE) {
        return null
    }

    return {
        values: surveyRatingResults.data,
        total: surveyRatingResults.total,
    }
}

/**
 * Core NPS calculation logic - works with raw data arrays
 */
function calculateNPSFromRawData(rawData: NPSRawData): NPSBreakdown {
    if (rawData.total === 0) {
        return { total: 0, promoters: 0, passives: 0, detractors: 0, score: '0.0' }
    }

    const promoters = rawData.values.slice(NPS_PROMOTER_MIN, NPS_SCALE_SIZE).reduce((acc, curr) => acc + curr, 0)
    const passives = rawData.values.slice(NPS_PASSIVE_MIN, NPS_PROMOTER_MIN).reduce((acc, curr) => acc + curr, 0)
    const detractors = rawData.values.slice(0, NPS_PASSIVE_MIN).reduce((acc, curr) => acc + curr, 0)

    const score = ((promoters - detractors) / rawData.total) * 100

    return {
        total: rawData.total,
        promoters,
        passives,
        detractors,
        score: score.toFixed(1),
    }
}

export function calculateNpsBreakdownFromProcessedData(processedData: QuestionProcessedResponses): NPSBreakdown | null {
    const rawData = extractNPSRawData(processedData)
    return rawData ? calculateNPSFromRawData(rawData) : null
}

export function calculateNpsBreakdown(surveyRatingResults: SurveyRatingResults[number]): NPSBreakdown | null {
    const rawData = extractNPSRawDataFromLegacy(surveyRatingResults)
    return rawData ? calculateNPSFromRawData(rawData) : null
}

// Helper to escape special characters in SQL strings
function escapeSqlString(value: string): string {
    return value.replace(/['\\]/g, '\\$&')
}

export function getSurveyResponse(question: SurveyQuestion, index: number): string {
    const { indexBasedKey, idBasedKey } = getResponseFieldWithId(index, question.id)

    if (question.type === SurveyQuestionType.MultipleChoice) {
        return `if(
        JSONHas(events.properties, '${idBasedKey}') AND length(JSONExtractArrayRaw(events.properties, '${idBasedKey}')) > 0,
        JSONExtractArrayRaw(events.properties, '${idBasedKey}'),
        JSONExtractArrayRaw(events.properties, '${indexBasedKey}')
    )`
    }

    return `COALESCE(
        NULLIF(JSONExtractString(events.properties, '${idBasedKey}'), ''),
        NULLIF(JSONExtractString(events.properties, '${indexBasedKey}'), '')
    )`
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
        const questionId = filter.key.split(`${SurveyEventProperties.SURVEY_RESPONSE}_`).at(-1)
        const question = survey.questions.find((question) => question.id === questionId)
        if (!questionId || !question) {
            continue
        }

        const questionIndex = survey.questions.findIndex((question) => question.id === questionId)

        // Create the condition for this filter
        let condition = ''
        const escapedValue = escapeSqlString(String(filter.value))

        // Handle different operators
        switch (filter.operator) {
            case 'exact':
            case 'is_not':
                if (Array.isArray(filter.value)) {
                    const valueList = filter.value.map((v) => `'${escapeSqlString(String(v))}'`).join(', ')
                    condition = `(${getSurveyResponse(question, questionIndex)} ${
                        filter.operator === 'is_not' ? 'NOT IN' : 'IN'
                    } (${valueList}))`
                } else {
                    condition = `(${getSurveyResponse(question, questionIndex)} ${
                        filter.operator === 'is_not' ? '!=' : '='
                    } '${escapedValue}')`
                }
                break
            case 'icontains':
                if (question.type !== SurveyQuestionType.MultipleChoice) {
                    condition = `(${getSurveyResponse(question, questionIndex)} ILIKE '%${escapedValue}%')`
                } else {
                    condition = `(arrayExists(x -> x ilike '%${escapedValue}%', ${getSurveyResponse(question, questionIndex)}))`
                }
                break
            case 'not_icontains':
                if (question.type !== SurveyQuestionType.MultipleChoice) {
                    condition = `(NOT ${getSurveyResponse(question, questionIndex)} ILIKE '%${escapedValue}%')`
                } else {
                    condition = `(NOT arrayExists(x -> x ilike '%${escapedValue}%', ${getSurveyResponse(question, questionIndex)}))`
                }
                break
            case 'regex':
                if (question.type !== SurveyQuestionType.MultipleChoice) {
                    condition = `(match(${getSurveyResponse(question, questionIndex)}, '${escapedValue}'))`
                } else {
                    condition = `(arrayExists(x -> match(x, '${escapedValue}'), ${getSurveyResponse(question, questionIndex)}))`
                }
                break
            case 'not_regex':
                if (question.type !== SurveyQuestionType.MultipleChoice) {
                    condition = `(NOT match(${getSurveyResponse(question, questionIndex)}, '${escapedValue}'))`
                } else {
                    condition = `(NOT arrayExists(x -> match(x, '${escapedValue}'), ${getSurveyResponse(question, questionIndex)}))`
                }
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

export const DATE_FORMAT = 'YYYY-MM-DDTHH:mm:ss'

export function getSurveyStartDateForQuery(survey: Survey): string {
    return dayjs(survey.created_at).utc().startOf('day').format(DATE_FORMAT)
}

export function getSurveyEndDateForQuery(survey: Survey): string {
    return survey.end_date
        ? dayjs(survey.end_date).utc().endOf('day').format(DATE_FORMAT)
        : dayjs().utc().endOf('day').format(DATE_FORMAT)
}

export function buildPartialResponsesFilter(survey: Survey): string {
    if (!survey.enable_partial_responses) {
        return `AND (
        NOT JSONHas(properties, '${SurveyEventProperties.SURVEY_COMPLETED}')
        OR JSONExtractBool(properties, '${SurveyEventProperties.SURVEY_COMPLETED}') = true
    )`
    }

    return `AND uuid in (
        SELECT
            argMax(uuid, timestamp)
        FROM events
        WHERE and(
            equals(event, '${SurveyEventName.SENT}'),
            equals(JSONExtractString(properties, '${SurveyEventProperties.SURVEY_ID}'), '${survey.id}'),
            greaterOrEquals(timestamp, '${getSurveyStartDateForQuery(survey)}'),
            lessOrEquals(timestamp, '${getSurveyEndDateForQuery(survey)}')
        )
        GROUP BY
            if(
                JSONHas(properties, '${SurveyEventProperties.SURVEY_SUBMISSION_ID}'),
                JSONExtractString(properties, '${SurveyEventProperties.SURVEY_SUBMISSION_ID}'),
                toString(uuid)
            )
    ) --- Filter to ensure we only get one response per ${SurveyEventProperties.SURVEY_SUBMISSION_ID}`
}

export function sanitizeSurvey(survey: Partial<Survey>): Partial<Survey> {
    const sanitizedQuestions =
        survey.questions?.map((question) => ({
            ...question,
            question: sanitizeHTML(question.question ?? ''),
            description: sanitizeHTML(question.description ?? ''),
        })) || []

    const sanitizedAppearance = sanitizeSurveyAppearance(survey.appearance, survey.enable_partial_responses ?? false)

    // Remove widget-specific fields if survey type is not Widget
    if (survey.type !== SurveyType.Widget && sanitizedAppearance) {
        delete sanitizedAppearance.widgetType
        delete sanitizedAppearance.widgetLabel
        delete sanitizedAppearance.widgetColor
    }

    return {
        ...survey,
        conditions: sanitizeSurveyDisplayConditions(survey.conditions),
        questions: sanitizedQuestions,
        appearance: sanitizedAppearance,
    }
}
