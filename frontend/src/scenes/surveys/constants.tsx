import { Link } from '@posthog/lemon-ui'
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
                type: SurveyQuestionType.Open,
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
                type: SurveyQuestionType.Link,
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
                type: SurveyQuestionType.MultipleChoice,
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

export enum SurveyTemplateTypes {
    Interview = 'User Interview',
    NPS = 'Net Promoter Score (NPS)',
    CSAT = 'Customer Satisfaction Score (CSAT)',
    CES = 'Customer Effort Score (CES)',
    CCR = 'Customer Churn Rate (CCR)',
    Superhuman = 'Product Market Fit (Superhuman)',
}

export const defaultSurveyTemplates = [
    {
        type: SurveyTemplateTypes.Interview,
        questions: [
            {
                type: SurveyQuestionType.Link,
                question: 'Would you be interested in participating in a customer interview?',
                description: 'We are looking for feedback on our product and would love to hear from you!',
                link: 'https://calendly.com/',
            },
        ],
        description: (
            <>
                User interviews provide a more complete picture into your user's experience because you have the
                opportunity to ask follow up questions. Find out how to conduct successful user interviews in{' '}
                <Link to="https://posthog.com/blog/interview-snapshot-guide" targetBlankIcon target="_blank">
                    our guide here
                </Link>
            </>
        ),
    },
    {
        type: SurveyTemplateTypes.NPS,
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
        description:
            "NPS is primarily a long-term, relational metric that measures how likely a customer is to recommend your product or brand to others. Think of it as a pulse check on your customer's overall satisfaction with the product as a whole.",
    },
    {
        type: SurveyTemplateTypes.Superhuman,
        questions: [
            {
                type: SurveyQuestionType.SingleChoice,
                question: 'How would you feel if you could no longer use PostHog?',
                choices: ['Not disappointed', 'Somewhat disappointed', 'Very disappointed'],
            },
        ],
        description:
            "Ask your users how they would feel if they could no longer use your product. If 40% of your users say they would be 'very disappointed', you've found product market fit.",
    },
    {
        type: SurveyTemplateTypes.CSAT,
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
        description:
            'CSAT surveys are a great way to measure customer satisfaction for a particular interaction or feature with the product. They are short and easy to answer, making them a great way to get feedback from your users for specific product improvements.',
    },
    {
        type: SurveyTemplateTypes.CES,
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
        description:
            'CES surveys are used to measure how easy a product or service was to use. Customer effort is a good indicator of customer loyalty, and can be used alongside churn surveys to understand if customer effort impacts churn rates.',
    },
    {
        type: SurveyTemplateTypes.CCR,
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
            {
                type: SurveyQuestionType.Open,
                question: "Anything else you'd like to share?",
            },
        ],
        description:
            "Customer churn can be expensive. Acquiring new customers is often more expensive than retaining existing ones, so it's important to understand why your customers are leaving.",
    },
]
