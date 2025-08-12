// Survey schema definitions - importing only the enums and simple types to avoid circular references
import type {
    SurveyMatchType,
    SurveyPosition,
    SurveyQuestionDescriptionContentType,
    SurveyQuestionType,
    SurveyType,
    SurveyWidgetType,
} from '~/types'

// Re-export the enums for the schema system
export { SurveyMatchType, SurveyPosition, SurveyQuestionType, SurveyType, SurveyWidgetType }
export type { SurveyQuestionDescriptionContentType }

// Survey creation schema matching PostHog Survey model format
export interface SurveyCreationSchema {
    name: string
    description: string
    type: SurveyType
    questions: SurveyQuestionSchema[]
    should_launch?: boolean
    conditions?: SurveyDisplayConditionsSchema
    appearance?: SurveyAppearanceSchema
    start_date?: string
    end_date?: string
    responses_limit?: number
    iteration_count?: number
    iteration_frequency_days?: number
    archived?: boolean
    enable_partial_responses?: boolean
}

// Question schema matching PostHog Survey model format
export interface SurveyQuestionSchema {
    type: SurveyQuestionType
    question: string
    description?: string
    descriptionContentType?: SurveyQuestionDescriptionContentType
    optional?: boolean
    buttonText?: string

    // Choice questions
    choices?: string[]
    shuffleOptions?: boolean
    hasOpenChoice?: boolean

    // Rating questions
    display?: 'number' | 'emoji'
    scale?: number
    lowerBoundLabel?: string
    upperBoundLabel?: string

    // Link questions
    link?: string

    // Branching logic
    branching?: {
        type: 'next_question' | 'end' | 'response_based' | 'specific_question'
        responseValues?: Record<string, string | number>
        index?: number
    }
}

// Display conditions matching PostHog Survey model format
export interface SurveyDisplayConditionsSchema {
    url?: string
    urlMatchType?: SurveyMatchType
    selector?: string
    deviceTypes?: string[]
    deviceTypesMatchType?: SurveyMatchType
    linkedFlagVariant?: string
    seenSurveyWaitPeriodInDays?: number
    actions?: {
        values: Array<{
            id: number
            name: string
        }>
    }
}

// Appearance schema matching PostHog Survey model format
export interface SurveyAppearanceSchema {
    backgroundColor?: string
    borderColor?: string
    position?: SurveyPosition
    whiteLabel?: boolean
    thankYouMessageHeader?: string
    thankYouMessageDescription?: string
    thankYouMessageDescriptionContentType?: SurveyQuestionDescriptionContentType
    thankYouMessageCloseButtonText?: string
    shuffleQuestions?: boolean
    surveyPopupDelaySeconds?: number
    widgetType?: SurveyWidgetType
    widgetLabel?: string
    widgetSelector?: string
    widgetColor?: string
    maxWidth?: string
    zIndex?: string
    placeholder?: string
    inputBackground?: string
    buttonColor?: string
    buttonTextColor?: string
    textColor?: string
    textSubtleColor?: string
    ratingButtonColor?: string
    ratingButtonActiveColor?: string
}
