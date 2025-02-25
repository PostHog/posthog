import DOMPurify from 'dompurify'
import { SurveyRatingResults } from 'scenes/surveys/surveyLogic'

import { SurveyAppearance } from '~/types'

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
    return questionIndex === 0 ? '$survey_response' : `$survey_response_${questionIndex}`
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
