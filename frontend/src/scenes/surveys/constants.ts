import { FeatureFlagFilters, Survey, SurveyQuestionType, SurveyType, SurveyUrlMatchType } from '~/types'

export const SURVEY_EVENT_NAME = 'survey sent'
export const SURVEY_RESPONSE_PROPERTY = '$survey_response'

export const SurveyQuestionLabel = {
    [SurveyQuestionType.Open]: 'Open text',
    [SurveyQuestionType.Rating]: 'Rating',
    [SurveyQuestionType.Link]: 'Link',
    [SurveyQuestionType.SingleChoice]: 'Single choice select',
    [SurveyQuestionType.MultipleChoice]: 'Multiple choice select',
}

export const SurveyUrlMatchTypeLabels = {
    [SurveyUrlMatchType.Contains]: '∋ contains',
    [SurveyUrlMatchType.Regex]: '∼ matches regex',
    [SurveyUrlMatchType.Exact]: '= equals',
}

export const defaultSurveyAppearance = {
    backgroundColor: '#eeeded',
    submitButtonText: 'Submit',
    submitButtonColor: 'black',
    ratingButtonColor: 'white',
    ratingButtonActiveColor: 'black',
    borderColor: '#c9c6c6',
    placeholder: '',
    whiteLabel: false,
    displayThankYouMessage: true,
    thankYouMessageHeader: 'Thank you for your feedback!',
    position: 'right',
}

export const defaultSurveyFieldValues = {
    [SurveyQuestionType.Open]: {
        questions: [
            {
                question: 'Give us feedback on our product!',
                description: '',
            },
        ],
        appearance: {
            submitButtonText: 'Submit',
            thankYouMessageHeader: 'Thank you for your feedback!',
        },
    },
    [SurveyQuestionType.Link]: {
        questions: [
            {
                question: 'Do you want to join our upcoming webinar?',
                description: '',
            },
        ],
        appearance: {
            submitButtonText: 'Register',
            thankYouMessageHeader: 'Redirecting ...',
        },
    },
    [SurveyQuestionType.Rating]: {
        questions: [
            {
                question: 'How likely are you to recommend us to a friend?',
                description: '',
                display: 'number',
                scale: 10,
                lowerBoundLabel: 'Unlikely',
                upperBoundLabel: 'Very likely',
            },
        ],
        appearance: {
            thankYouMessageHeader: 'Thank you for your feedback!',
        },
    },
    [SurveyQuestionType.SingleChoice]: {
        questions: [
            {
                question: 'Have you found this tutorial useful?',
                description: '',
                choices: ['Yes', 'No'],
            },
        ],
        appearance: {
            submitButtonText: 'Submit',
            thankYouMessageHeader: 'Thank you for your feedback!',
        },
    },
    [SurveyQuestionType.MultipleChoice]: {
        questions: [
            {
                question: 'Which types of content would you like to see more of?',
                description: '',
                choices: ['Tutorials', 'Customer case studies', 'Product announcements'],
            },
        ],
        appearance: {
            submitButtonText: 'Submit',
            thankYouMessageHeader: 'Thank you for your feedback!',
        },
    },
}

export interface NewSurvey
    extends Pick<
        Survey,
        | 'name'
        | 'description'
        | 'type'
        | 'conditions'
        | 'questions'
        | 'start_date'
        | 'end_date'
        | 'linked_flag'
        | 'targeting_flag'
        | 'archived'
        | 'appearance'
    > {
    id: 'new'
    linked_flag_id: number | undefined
    targeting_flag_filters: Pick<FeatureFlagFilters, 'groups'> | undefined
}

export const NEW_SURVEY: NewSurvey = {
    id: 'new',
    name: '',
    description: '',
    questions: [
        {
            type: SurveyQuestionType.Open,
            question: defaultSurveyFieldValues[SurveyQuestionType.Open].questions[0].question,
            description: defaultSurveyFieldValues[SurveyQuestionType.Open].questions[0].description,
        },
    ],
    type: SurveyType.Popover,
    linked_flag_id: undefined,
    targeting_flag_filters: undefined,
    linked_flag: null,
    targeting_flag: null,
    start_date: null,
    end_date: null,
    conditions: null,
    archived: false,
    appearance: defaultSurveyAppearance,
}
