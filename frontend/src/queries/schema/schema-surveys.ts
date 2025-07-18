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

// Simplified survey creation schema for the LLM tool - avoiding complex nested types
export interface SurveyCreationSchema {
    name: string
    description: string
    type: SurveyType
    questions: SurveyQuestionSchema[]
    should_launch?: boolean
    conditions?: SurveyDisplayConditionsSchema
    appearance?: SurveyAppearanceSchema
    enable_partial_responses?: boolean
    start_date?: string
    end_date?: string
    responses_limit?: number
    iteration_count?: number
    iteration_frequency_days?: number
}

// Simplified question schema
export interface SurveyQuestionSchema {
    type: SurveyQuestionType
    question: string
    id?: string
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
    scale?: 5 | 7 | 10
    lowerBoundLabel?: string
    upperBoundLabel?: string
    skipSubmitButton?: boolean

    // Link questions
    link?: string
}

// Simplified display conditions
export interface SurveyDisplayConditionsSchema {
    url?: string
    selector?: string
    seenSurveyWaitPeriodInDays?: number
    urlMatchType?: SurveyMatchType
    deviceTypes?: string[]
    deviceTypesMatchType?: SurveyMatchType
}

// Simplified appearance schema
export interface SurveyAppearanceSchema {
    backgroundColor?: string
    submitButtonColor?: string
    submitButtonText?: string
    submitButtonTextColor?: string
    ratingButtonColor?: string
    ratingButtonActiveColor?: string
    borderColor?: string
    placeholder?: string
    whiteLabel?: boolean
    displayThankYouMessage?: boolean
    thankYouMessageHeader?: string
    thankYouMessageDescription?: string
    thankYouMessageDescriptionContentType?: SurveyQuestionDescriptionContentType
    thankYouMessageCloseButtonText?: string
    autoDisappear?: boolean
    position?: SurveyPosition
    zIndex?: string
    shuffleQuestions?: boolean
    surveyPopupDelaySeconds?: number
    widgetType?: SurveyWidgetType
    widgetSelector?: string
    widgetLabel?: string
    widgetColor?: string
    fontFamily?: string
    disabledButtonOpacity?: string
    maxWidth?: string
    textSubtleColor?: string
    inputBackground?: string
    boxPadding?: string
    boxShadow?: string
    borderRadius?: string
}
