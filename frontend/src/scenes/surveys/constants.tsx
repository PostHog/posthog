import { IconAreaChart, IconComment, IconGridView, IconLink, IconListView } from 'lib/lemon-ui/icons'
import { allOperatorsMapping } from 'lib/utils'

import {
    Survey,
    SurveyAppearance,
    SurveyMatchType,
    SurveyQuestionDescriptionContentType,
    SurveyQuestionType,
    SurveySchedule,
    SurveyType,
} from '~/types'

export const SURVEY_EVENT_NAME = 'survey sent'
export const SURVEY_RESPONSE_PROPERTY = '$survey_response'
export const SURVEY_PAGE_SIZE = 100

export const SurveyQuestionLabel: Record<SurveyQuestionType, string> = {
    [SurveyQuestionType.Open]: 'Freeform text',
    [SurveyQuestionType.Rating]: 'Rating',
    [SurveyQuestionType.Link]: 'Link',
    [SurveyQuestionType.SingleChoice]: 'Single choice select',
    [SurveyQuestionType.MultipleChoice]: 'Multiple choice select',
}

// Create SurveyMatchTypeLabels using allOperatorsMapping
export const SurveyMatchTypeLabels = {
    [SurveyMatchType.Exact]: allOperatorsMapping[SurveyMatchType.Exact],
    [SurveyMatchType.IsNot]: allOperatorsMapping[SurveyMatchType.IsNot],
    [SurveyMatchType.Contains]: allOperatorsMapping[SurveyMatchType.Contains],
    [SurveyMatchType.NotIContains]: allOperatorsMapping[SurveyMatchType.NotIContains],
    [SurveyMatchType.Regex]: allOperatorsMapping[SurveyMatchType.Regex],
    [SurveyMatchType.NotRegex]: allOperatorsMapping[SurveyMatchType.NotRegex],
}

export const defaultSurveyAppearance = {
    fontFamily: 'system-ui' as SurveyAppearance['fontFamily'],
    backgroundColor: '#eeeded',
    submitButtonColor: 'black',
    submitButtonTextColor: 'white',
    ratingButtonColor: 'white',
    ratingButtonActiveColor: 'black',
    borderColor: '#c9c6c6',
    placeholder: 'Start typing...',
    whiteLabel: false,
    displayThankYouMessage: true,
    thankYouMessageHeader: 'Thank you for your feedback!',
    position: 'right',
    widgetType: 'tab' as const,
    widgetLabel: 'Feedback',
    widgetColor: 'black',
}

export const defaultSurveyFieldValues = {
    [SurveyQuestionType.Open]: {
        questions: [
            {
                type: SurveyQuestionType.Open,
                question: 'Give us feedback on our product!',
                description: '',
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
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
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
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
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
                display: 'number',
                scale: 10,
                lowerBoundLabel: 'Unlikely',
                upperBoundLabel: 'Very likely',
                buttonText: 'Submit',
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
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
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
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
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
        | 'targeting_flag_filters'
        | 'responses_limit'
        | 'iteration_count'
        | 'iteration_frequency_days'
        | 'iteration_start_dates'
        | 'current_iteration'
        | 'response_sampling_start_date'
        | 'response_sampling_interval_type'
        | 'response_sampling_interval'
        | 'response_sampling_limit'
        | 'schedule'
        | 'enable_partial_responses'
    > {
    id: 'new'
    linked_flag_id: number | null
}

export const NEW_SURVEY: NewSurvey = {
    id: 'new',
    name: '',
    description: '',
    schedule: SurveySchedule.Once,
    questions: [
        {
            type: SurveyQuestionType.Open,
            question: defaultSurveyFieldValues[SurveyQuestionType.Open].questions[0].question,
            description: defaultSurveyFieldValues[SurveyQuestionType.Open].questions[0].description,
            descriptionContentType:
                defaultSurveyFieldValues[SurveyQuestionType.Open].questions[0].descriptionContentType,
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
    responses_limit: null,
    iteration_count: null,
    iteration_frequency_days: null,
}

export enum SurveyTemplateType {
    OpenFeedback = 'Open feedback',
    Interview = 'User interview',
    NPS = 'Net promoter score (NPS)',
    CSAT = 'Customer satisfaction score (CSAT)',
    CES = 'Customer effort score (CES)',
    CCR = 'Customer churn rate (CCR)',
    PMF = 'Product-market fit (PMF)',
    ErrorTracking = 'Capture exceptions',
}

type SurveyTemplate = Partial<Survey> & {
    templateType: SurveyTemplateType
}

export const defaultSurveyTemplates: SurveyTemplate[] = [
    {
        type: SurveyType.Popover,
        templateType: SurveyTemplateType.OpenFeedback,
        questions: [
            {
                type: SurveyQuestionType.Open,
                question: 'What can we do to improve our product?',
                description: '',
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
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
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
                buttonText: 'Schedule',
                link: null,
            },
        ],
        appearance: {
            thankYouMessageHeader: 'Looking forward to chatting with you!',
        },
        description: 'Send users straight to your calendar.',
    },
    {
        type: SurveyType.Popover,
        templateType: SurveyTemplateType.NPS,
        questions: [
            {
                type: SurveyQuestionType.Rating,
                question: 'How likely are you to recommend us to a friend?',
                description: '',
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
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
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
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
                question: 'PostHog made it easy for me to resolve my issue',
                description: '',
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
                display: 'number',
                scale: 7,
                lowerBoundLabel: 'Strongly disagree',
                upperBoundLabel: 'Strongly agree',
            },
        ],
        description: 'Works well with churn surveys.',
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

export const errorTrackingSurvey: SurveyTemplate = {
    type: SurveyType.Popover,
    templateType: SurveyTemplateType.ErrorTracking,
    questions: [
        {
            type: SurveyQuestionType.Open,
            question: 'Looks like something went wrong',
            description: "We've captured the basics, but please tell us more to help us fix it!",
            descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
        },
    ],
    conditions: {
        url: '',
        seenSurveyWaitPeriodInDays: 14,
        actions: null,
        events: { repeatedActivation: true, values: [{ name: '$exception' }] },
    },
    appearance: {
        surveyPopupDelaySeconds: 2,
    },
    description: 'Ask users for context when they hit an exception.',
}

export const WEB_SAFE_FONTS = [
    { value: 'system-ui', label: 'system-ui (default)' },
    { value: 'inherit', label: 'inherit (uses the font family of your website)' },
    { value: 'Arial', label: 'Arial' },
    { value: 'Verdana', label: 'Verdana' },
    { value: 'Tahoma', label: 'Tahoma' },
    { value: 'Trebuchet MS', label: 'Trebuchet MS' },
    { value: 'Helvetica', label: 'Helvetica' },
    { value: 'Times New Roman', label: 'Times New Roman' },
    { value: 'Georgia', label: 'Georgia' },
    { value: 'Courier New', label: 'Courier New' },
] as const

export const NPS_DETRACTOR_LABEL = 'Detractors'
export const NPS_PASSIVE_LABEL = 'Passives'
export const NPS_PROMOTER_LABEL = 'Promoters'

export const QUESTION_TYPE_ICON_MAP = {
    [SurveyQuestionType.Open]: <IconComment className="text-muted" />,
    [SurveyQuestionType.Link]: <IconLink className="text-muted" />,
    [SurveyQuestionType.Rating]: <IconAreaChart className="text-muted" />,
    [SurveyQuestionType.SingleChoice]: <IconListView className="text-muted" />,
    [SurveyQuestionType.MultipleChoice]: <IconGridView className="text-muted" />,
}
