import DOMPurify from 'dompurify'

import { PropertyOperator, SurveyAppearance, SurveyMatchType } from '~/types'

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

export function getSurveyMatchTypeToPropertyOperator(surveyMatchType?: SurveyMatchType): PropertyOperator {
    if (!surveyMatchType) {
        return PropertyOperator.IContains
    }

    switch (surveyMatchType) {
        case SurveyMatchType.Contains:
            return PropertyOperator.IContains
        case SurveyMatchType.NotIContains:
            return PropertyOperator.NotIContains
        case SurveyMatchType.Regex:
            return PropertyOperator.Regex
        case SurveyMatchType.NotRegex:
            return PropertyOperator.NotRegex
        case SurveyMatchType.Exact:
            return PropertyOperator.Exact
        case SurveyMatchType.IsNot:
            return PropertyOperator.IsNot
        default:
            return PropertyOperator.IContains
    }
}
