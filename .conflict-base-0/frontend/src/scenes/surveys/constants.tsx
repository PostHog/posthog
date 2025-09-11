import { IconAreaChart, IconComment, IconGridView, IconLink, IconListView } from 'lib/lemon-ui/icons'
import { allOperatorsMapping } from 'lib/utils'

import {
    Survey,
    SurveyAppearance,
    SurveyMatchType,
    SurveyPosition,
    SurveyQuestionDescriptionContentType,
    SurveyQuestionType,
    SurveySchedule,
    SurveyType,
    SurveyWidgetType,
} from '~/types'

export const SURVEY_PAGE_SIZE = 100

export const LINK_PAGE_SIZE = 100

export const SurveyQuestionLabel: Record<SurveyQuestionType, string> = {
    [SurveyQuestionType.Open]: 'Freeform text',
    [SurveyQuestionType.Rating]: 'Rating',
    [SurveyQuestionType.Link]: 'Link',
    [SurveyQuestionType.SingleChoice]: 'Single choice select',
    [SurveyQuestionType.MultipleChoice]: 'Multiple choice select',
}

// Rating scale constants
export const SURVEY_RATING_SCALE = {
    EMOJI_3_POINT: 3,
    LIKERT_5_POINT: 5,
    LIKERT_7_POINT: 7,
    NPS_10_POINT: 10,
} as const

export type SurveyRatingScaleValue = (typeof SURVEY_RATING_SCALE)[keyof typeof SURVEY_RATING_SCALE]

// Create SurveyMatchTypeLabels using allOperatorsMapping
export const SurveyMatchTypeLabels = {
    [SurveyMatchType.Exact]: allOperatorsMapping[SurveyMatchType.Exact],
    [SurveyMatchType.IsNot]: allOperatorsMapping[SurveyMatchType.IsNot],
    [SurveyMatchType.Contains]: allOperatorsMapping[SurveyMatchType.Contains],
    [SurveyMatchType.NotIContains]: allOperatorsMapping[SurveyMatchType.NotIContains],
    [SurveyMatchType.Regex]: allOperatorsMapping[SurveyMatchType.Regex],
    [SurveyMatchType.NotRegex]: allOperatorsMapping[SurveyMatchType.NotRegex],
}

// Sync with posthog/constants.py
export const defaultSurveyAppearance = {
    fontFamily: 'inherit',
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
    position: SurveyPosition.Right,
    widgetType: SurveyWidgetType.Tab,
    widgetLabel: 'Feedback',
    widgetColor: 'black',
    zIndex: '2147482647',
    disabledButtonOpacity: '0.6',
    maxWidth: '300px',
    textSubtleColor: '#939393',
    inputBackground: 'white',
    boxPadding: '20px 24px',
    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
    borderRadius: '10px',
    shuffleQuestions: false,
    surveyPopupDelaySeconds: undefined,
} as const satisfies SurveyAppearance

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
                scale: SURVEY_RATING_SCALE.NPS_10_POINT,
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
    enable_partial_responses: true,
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
    TrafficAttribution = 'Traffic attribution',
    FeatureRequest = 'Feature request',
    OnboardingFeedback = 'Onboarding feedback',
    BetaFeedback = 'Beta feedback',
}

export type SurveyTemplate = Partial<Survey> & {
    templateType: SurveyTemplateType
    tagType?: 'success' | 'primary' | 'completion' | 'default'
    category?: 'Metrics' | 'Product' | 'Business' | 'General'
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
        tagType: 'default',
        category: 'General',
        appearance: defaultSurveyAppearance,
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
                scale: SURVEY_RATING_SCALE.NPS_10_POINT,
                lowerBoundLabel: 'Unlikely',
                upperBoundLabel: 'Very likely',
                skipSubmitButton: true,
            },
            {
                type: SurveyQuestionType.Open,
                question: 'What else can we do to improve your experience?',
                description: '',
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
            },
        ],
        description: 'Get an industry-recognized benchmark.',
        tagType: 'success',
        category: 'Metrics',
        appearance: defaultSurveyAppearance,
    },
    {
        type: SurveyType.Popover,
        templateType: SurveyTemplateType.PMF,
        questions: [
            {
                type: SurveyQuestionType.SingleChoice,
                question: 'How often do you use our product?',
                choices: ['Every day', 'A few times a week', 'A few times a month', 'A few times a year', 'Never'],
                skipSubmitButton: true,
            },
            {
                type: SurveyQuestionType.SingleChoice,
                question: 'How would you feel if you could no longer our product?',
                choices: ['Not disappointed', 'Somewhat disappointed', 'Very disappointed'],
                skipSubmitButton: true,
            },
        ],
        description: "40% 'very disappointed' signals product-market fit.",
        tagType: 'success',
        category: 'Metrics',
        appearance: defaultSurveyAppearance,
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
                scale: SURVEY_RATING_SCALE.LIKERT_5_POINT,
                lowerBoundLabel: 'Very dissatisfied',
                upperBoundLabel: 'Very satisfied',
                skipSubmitButton: true,
            },
            {
                type: SurveyQuestionType.Open,
                question: 'Please help us do better! Can you tell us more about the ratings you gave us?',
                description: '',
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
            },
        ],
        description: 'Works best after a checkout or support flow.',
        tagType: 'success',
        category: 'Metrics',
        appearance: defaultSurveyAppearance,
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
        tagType: 'completion',
        category: 'Business',
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
                scale: SURVEY_RATING_SCALE.LIKERT_7_POINT,
                lowerBoundLabel: 'Strongly disagree',
                upperBoundLabel: 'Strongly agree',
                skipSubmitButton: true,
            },
        ],
        description: 'Works well with churn surveys.',
        tagType: 'success',
        category: 'Metrics',
        appearance: defaultSurveyAppearance,
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
                skipSubmitButton: true,
                hasOpenChoice: true,
            },
            {
                type: SurveyQuestionType.Open,
                question: 'What could we have done better?',
                description: '',
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
            },
        ],
        description: 'Find out if it was something you said.',
        tagType: 'completion',
        category: 'Business',
        appearance: defaultSurveyAppearance,
    },
    {
        type: SurveyType.Popover,
        templateType: SurveyTemplateType.TrafficAttribution,
        questions: [
            {
                type: SurveyQuestionType.SingleChoice,
                question: 'Where did you hear about us?',
                choices: [
                    'Search engine (Google, Bing, etc)',
                    'AI assistant (like ChatGPT)',
                    'Social media (X, LinkedIn, YouTube, etc)',
                    'Referral from a friend or colleague',
                    'Other',
                ],
                hasOpenChoice: true,
                skipSubmitButton: true,
            },
            {
                type: SurveyQuestionType.Open,
                question: 'What made you decide to visit our page?',
                description: '',
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
            },
        ],
        description: 'Find out where your traffic is coming from.',
        tagType: 'completion',
        category: 'Business',
        appearance: defaultSurveyAppearance,
    },
    {
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
        description: 'Ask users for context when they hit an exception.',
        tagType: 'default',
        category: 'General',
        appearance: {
            ...defaultSurveyAppearance,
            surveyPopupDelaySeconds: 2,
        },
    },
    {
        type: SurveyType.Popover,
        templateType: SurveyTemplateType.FeatureRequest,
        questions: [
            {
                type: SurveyQuestionType.SingleChoice,
                question: 'What feature would you like to see next?',
                choices: [
                    'Better analytics dashboard',
                    'Mobile app',
                    'API improvements',
                    'Integration with more tools',
                    'Other',
                ],
                hasOpenChoice: true,
                skipSubmitButton: true,
            },
            {
                type: SurveyQuestionType.Open,
                question: 'Tell us more about how this feature would help you.',
                description: '',
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
            },
        ],
        description: 'Let users vote on your roadmap priorities.',
        tagType: 'primary',
        category: 'Product',
        appearance: defaultSurveyAppearance,
    },
    {
        type: SurveyType.Popover,
        templateType: SurveyTemplateType.OnboardingFeedback,
        questions: [
            {
                type: SurveyQuestionType.Rating,
                question: 'How was your onboarding experience?',
                description: '',
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
                display: 'emoji',
                scale: SURVEY_RATING_SCALE.LIKERT_5_POINT,
                lowerBoundLabel: 'Terrible',
                upperBoundLabel: 'Amazing',
                skipSubmitButton: true,
            },
            {
                type: SurveyQuestionType.Open,
                question: 'What was the most confusing part of getting started?',
                description: '',
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
            },
        ],
        conditions: {
            url: '',
            seenSurveyWaitPeriodInDays: 1,
            actions: null,
            events: null,
        },
        description: "Capture first impressions while they're fresh.",
        tagType: 'primary',
        category: 'Product',
        appearance: defaultSurveyAppearance,
    },
    {
        type: SurveyType.Popover,
        templateType: SurveyTemplateType.BetaFeedback,
        questions: [
            {
                type: SurveyQuestionType.Rating,
                question: 'How would you rate this new feature?',
                description: '',
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
                display: 'number',
                scale: SURVEY_RATING_SCALE.LIKERT_5_POINT,
                lowerBoundLabel: 'Needs work',
                upperBoundLabel: 'Love it',
                skipSubmitButton: true,
            },
            {
                type: SurveyQuestionType.MultipleChoice,
                question: 'What aspects need improvement?',
                choices: [
                    'Performance/speed',
                    'User interface',
                    'Functionality',
                    'Documentation',
                    "Nothing, it's great!",
                ],
                skipSubmitButton: true,
            },
            {
                type: SurveyQuestionType.Open,
                question: 'Any other feedback on this beta feature?',
                description: '',
                descriptionContentType: 'text' as SurveyQuestionDescriptionContentType,
            },
        ],
        description: 'Get targeted feedback on new features and betas.',
        tagType: 'primary',
        category: 'Product',
        appearance: defaultSurveyAppearance,
    },
]

export const WEB_SAFE_FONTS = [
    { value: 'inherit', label: 'inherit (uses your website font)' },
    { value: 'system-ui', label: 'system-ui' },
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

export const NPS_PROMOTER_VALUES = ['9', '10']
export const NPS_PASSIVE_VALUES = ['7', '8']
export const NPS_DETRACTOR_VALUES = ['0', '1', '2', '3', '4', '5', '6']

export const QUESTION_TYPE_ICON_MAP = {
    [SurveyQuestionType.Open]: <IconComment className="text-muted" />,
    [SurveyQuestionType.Link]: <IconLink className="text-muted" />,
    [SurveyQuestionType.Rating]: <IconAreaChart className="text-muted" />,
    [SurveyQuestionType.SingleChoice]: <IconListView className="text-muted" />,
    [SurveyQuestionType.MultipleChoice]: <IconGridView className="text-muted" />,
}

export const SURVEY_TYPE_LABEL_MAP = {
    [SurveyType.API]: 'API',
    [SurveyType.Widget]: 'Feedback Button',
    [SurveyType.Popover]: 'Popover',
    [SurveyType.FullScreen]: 'Full Screen',
    [SurveyType.ExternalSurvey]: 'Hosted Survey',
}

export const LOADING_SURVEY_RESULTS_TOAST_ID = 'survey-results-loading'

export const SCALE_LABELS: Record<SurveyRatingScaleValue, string> = {
    [SURVEY_RATING_SCALE.EMOJI_3_POINT]: '1 - 3',
    [SURVEY_RATING_SCALE.LIKERT_5_POINT]: '1 - 5',
    [SURVEY_RATING_SCALE.LIKERT_7_POINT]: '1 - 7',
    [SURVEY_RATING_SCALE.NPS_10_POINT]: '0 - 10',
}

export const SCALE_OPTIONS = {
    EMOJI: [
        { label: SCALE_LABELS[SURVEY_RATING_SCALE.EMOJI_3_POINT], value: SURVEY_RATING_SCALE.EMOJI_3_POINT },
        { label: SCALE_LABELS[SURVEY_RATING_SCALE.LIKERT_5_POINT], value: SURVEY_RATING_SCALE.LIKERT_5_POINT },
    ],
    NUMBER: [
        { label: SCALE_LABELS[SURVEY_RATING_SCALE.LIKERT_5_POINT], value: SURVEY_RATING_SCALE.LIKERT_5_POINT },
        {
            label: `${SCALE_LABELS[SURVEY_RATING_SCALE.LIKERT_7_POINT]} (7 Point Likert Scale)`,
            value: SURVEY_RATING_SCALE.LIKERT_7_POINT,
        },
        {
            label: `${SCALE_LABELS[SURVEY_RATING_SCALE.NPS_10_POINT]} (Net Promoter Score)`,
            value: SURVEY_RATING_SCALE.NPS_10_POINT,
        },
    ],
}

export enum SURVEY_CREATED_SOURCE {
    FEATURE_FLAGS = 'feature_flags',
    MAX_AI = 'max_ai',
    SURVEY_FORM = 'survey_form',
    SURVEY_EMPTY_STATE = 'survey_empty_state',
    EXPERIMENTS = 'experiments',
}

export enum SURVEY_EMPTY_STATE_EXPERIMENT_VARIANT {
    TEST = 'test', // new experience
    CONTROL = 'control', // current state
}

export enum SURVEY_FORM_INPUT_IDS {
    WAIT_PERIOD_INPUT = 'survey-wait-period-input',
}
