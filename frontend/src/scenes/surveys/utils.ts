import DOMPurify from 'dompurify'

import { SurveyAppearance } from '~/types'

const sanitizeConfig = { ADD_ATTR: ['target'] }

export function sanitizeHTML(html: string): string {
    return DOMPurify.sanitize(html, sanitizeConfig)
}

function sanitizeColor(color: string | undefined): string | undefined {
    if (!color) {
        return undefined
    }

    // test if the color is valid by adding a # to the beginning of the string
    if (!validateColor(`#${color}`, 'color')) {
        return `#${color}`
    }

    return color
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

export function validateColor(color: string | undefined, fieldName: string): string | undefined {
    if (!color) {
        return undefined
    }
    // Test if the color value is valid using CSS.supports
    const isValidColor = CSS.supports('color', color)
    return !isValidColor ? `Invalid color value for ${fieldName}. Please use a valid CSS color.` : undefined
}
