import { FeatureFlagFilters, Survey, SurveyQuestionType, SurveyType, SurveyUrlMatchType } from '~/types'

export const SURVEY_EVENT_NAME = 'survey sent'
export const SURVEY_RESPONSE_PROPERTY = '$survey_response'

export const SurveyQuestionLabel = {
    [SurveyQuestionType.Open]: 'Freeform text',
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
    submitButtonColor: 'black',
    ratingButtonColor: 'white',
    ratingButtonActiveColor: 'black',
    borderColor: '#c9c6c6',
    placeholder: 'Start typing...',
    whiteLabel: false,
    displayThankYouMessage: true,
    thankYouMessageHeader: 'Thank you for your feedback!',
    position: 'right',
}

export const defaultSurveyFieldValues = {
    [SurveyQuestionType.Open]: {
        questions: [
            {
                type: SurveyQuestionType.Open,
                question: 'Give us feedback on our product!',
                description: '',
                buttonText: 'Submit',
            },
        ],
        appearance: {
            thankYouMessageHeader: 'Thank you for your feedback!',
        },
    },
    [SurveyQuestionType.Link]: {
        questions: [
            {
                type: SurveyQuestionType.Link,
                question: 'Do you want to join our upcoming webinar?',
                description: '',
                buttonText: 'Register',
            },
        ],
        appearance: {
            thankYouMessageHeader: 'Thank you for your feedback!',
        },
    },
    [SurveyQuestionType.Rating]: {
        questions: [
            {
                type: SurveyQuestionType.Rating,
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
                type: SurveyQuestionType.SingleChoice,
                question: 'Have you found this tutorial useful?',
                description: '',
                choices: ['Yes', 'No'],
                buttonText: 'Submit',
            },
        ],
        appearance: {
            thankYouMessageHeader: 'Thank you for your feedback!',
        },
    },
    [SurveyQuestionType.MultipleChoice]: {
        questions: [
            {
                type: SurveyQuestionType.MultipleChoice,
                question: 'Which types of content would you like to see more of?',
                description: '',
                choices: ['Tutorials', 'Customer case studies', 'Product announcements'],
                buttonText: 'Submit',
            },
        ],
        appearance: {
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
    linked_flag_id: number | null
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
            buttonText: defaultSurveyFieldValues[SurveyQuestionType.Open].questions[0].buttonText,
        },
    ],
    type: SurveyType.Popover,
    linked_flag_id: null,
    targeting_flag_filters: undefined,
    linked_flag: null,
    targeting_flag: null,
    start_date: null,
    end_date: null,
    conditions: null,
    archived: false,
    appearance: defaultSurveyAppearance,
}

export enum SurveyTemplateType {
    OpenFeedback = 'Open feedback',
    Interview = 'User interview',
    NPS = 'Net promoter score (NPS)',
    CSAT = 'Customer satisfaction score (CSAT)',
    CES = 'Customer effort score (CES)',
    CCR = 'Customer churn rate (CCR)',
    PMF = 'Product-market fit (PMF)',
}

export const defaultSurveyTemplates = [
    {
        type: SurveyType.Popover,
        templateType: SurveyTemplateType.OpenFeedback,
        questions: [
            {
                type: SurveyQuestionType.Open,
                question: 'What can we do to improve our product?',
            },
        ],
        description: "Let your users share what's on their mind.",
    },
    {
        type: SurveyType.Popover,
        templateType: SurveyTemplateType.Interview,
        questions: [
            {
                type: SurveyQuestionType.Link,
                question: 'Would you be interested in participating in a customer interview?',
                description: 'We are looking for feedback on our product and would love to hear from you!',
                buttonText: 'Schedule',
            },
        ],
        description: <>Send users straight to your calendar.</>,
    },
    {
        type: SurveyType.Popover,
        templateType: SurveyTemplateType.NPS,
        questions: [
            {
                type: SurveyQuestionType.Rating,
                question: 'How likely are you to recommend us to a friend?',
                description: '',
                display: 'number',
                scale: 10,
                lowerBoundLabel: 'Unlikely',
                upperBoundLabel: 'Very likely',
            },
        ],
        description: 'Get an industry-recognized benchmark.',
    },
    {
        type: SurveyType.Popover,
        templateType: SurveyTemplateType.PMF,
        questions: [
            {
                type: SurveyQuestionType.SingleChoice,
                question: 'How would you feel if you could no longer use PostHog?',
                choices: ['Not disappointed', 'Somewhat disappointed', 'Very disappointed'],
            },
        ],
        description: "40% 'very disappointed' signals product-market fit.",
    },
    {
        type: SurveyType.Popover,
        templateType: SurveyTemplateType.CSAT,
        questions: [
            {
                type: SurveyQuestionType.Rating,
                question: 'How satisfied are you with PostHog surveys?',
                description: '',
                display: 'emoji',
                scale: 5,
                lowerBoundLabel: 'Very dissatisfied',
                upperBoundLabel: 'Very satisfied',
            },
        ],
        description: 'Works best after a checkout or support flow.',
        appearance: { ratingButtonColor: '#939393' },
    },
    {
        type: SurveyType.Popover,
        templateType: SurveyTemplateType.CES,
        questions: [
            {
                type: SurveyQuestionType.Rating,
                question: 'How easy was it to use our product?',
                description: '',
                display: 'emoji',
                scale: 5,
                lowerBoundLabel: 'Very difficult',
                upperBoundLabel: 'Very easy',
            },
        ],
        description: 'Works well with churn surveys.',
        appearance: { ratingButtonColor: '#939393' },
    },
    {
        type: SurveyType.Popover,
        templateType: SurveyTemplateType.CCR,
        questions: [
            {
                type: SurveyQuestionType.MultipleChoice,
                question: "We're sorry to see you go. What's your reason for unsubscribing?",
                choices: [
                    'I no longer need the product',
                    'I found a better product',
                    'I found the product too difficult to use',
                    'Other',
                ],
            },
        ],
        description: 'Find out if it was something you said.',
    },
]
