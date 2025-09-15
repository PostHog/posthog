import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { SurveysTabs } from 'scenes/surveys/surveysLogic'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import organizationCurrent from '~/mocks/fixtures/api/organizations/@current/@current.json'
import { toPaginatedResponse } from '~/mocks/handlers'
import {
    FeatureFlagBasicType,
    MultipleSurveyQuestion,
    PropertyFilterType,
    PropertyOperator,
    Survey,
    SurveyQuestionType,
    SurveySchedule,
    SurveyType,
} from '~/types'

import { SurveyEditSection, surveyLogic } from './surveyLogic'

const MOCK_BASIC_SURVEY: Survey = {
    id: '0187c279-bcae-0000-34f5-4f121921f005',
    name: 'basic survey',
    description: 'basic survey description',
    type: SurveyType.Popover,
    created_at: '2023-04-27T10:04:37.977401Z',
    created_by: {
        id: 1,
        uuid: '01863799-062b-0000-8a61-b2842d5f8642',
        distinct_id: 'Sopz9Z4NMIfXGlJe6W1XF98GOqhHNui5J5eRe0tBGTE',
        first_name: 'Employee 427',
        email: 'test2@posthog.com',
    },
    questions: [{ question: 'question 1?', type: SurveyQuestionType.Open }],
    conditions: null,
    linked_flag: null,
    linked_flag_id: null,
    targeting_flag: null,
    targeting_flag_filters: undefined,
    appearance: { backgroundColor: 'white', submitButtonColor: '#2C2C2C' },
    start_date: null,
    end_date: null,
    archived: false,
    responses_limit: null,
    iteration_count: null,
    iteration_frequency_days: null,
    schedule: SurveySchedule.Once,
}

const MOCK_SURVEY_WITH_MULTIPLE_OPTIONS: Survey = {
    id: '998FE805-F9EF-4F25-A5D1-B9549C4E2143',
    name: 'survey with multiple options',
    description: 'survey with multiple options description',
    type: SurveyType.Popover,
    created_at: '2023-04-27T10:04:37.977401Z',
    created_by: {
        id: 1,
        uuid: '01863799-062b-0000-8a61-b2842d5f8642',
        distinct_id: 'Sopz9Z4NMIfXGlJe6W1XF98GOqhHNui5J5eRe0tBGTE',
        first_name: 'Employee 427',
        email: 'test2@posthog.com',
    },
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
            shuffleOptions: true,
        },
    ],
    conditions: null,
    linked_flag: null,
    linked_flag_id: null,
    targeting_flag: null,
    targeting_flag_filters: undefined,
    appearance: { backgroundColor: 'white', submitButtonColor: '#2C2C2C' },
    start_date: null,
    end_date: null,
    archived: false,
    responses_limit: null,
    iteration_count: null,
    iteration_frequency_days: null,
    schedule: SurveySchedule.Once,
}

const MOCK_SURVEY_WITH_RELEASE_CONS: Survey = {
    id: '0187c279-bcae-0000-34f5-4f121921f006',
    name: 'survey with release conditions',
    description: 'survey with release conditions description',
    type: SurveyType.Popover,
    created_at: '2023-04-28T10:04:37.977401Z',
    created_by: {
        id: 1,
        uuid: '01863799-062b-0000-8a61-b2842d5f8642',
        distinct_id: 'Sopz9Z4NMIfXGlJe6W1XF98GOqhHNui5J5eRe0tBGTE',
        first_name: 'Employee 427',
        email: 'test2@posthog.com',
    },
    questions: [{ question: 'question 2?', type: SurveyQuestionType.Open }],
    appearance: { backgroundColor: 'white', submitButtonColor: '#2C2C2C' },
    conditions: {
        url: 'posthog',
        selector: '',
        events: { values: [{ name: 'user_subscribed' }] },
        actions: { values: [] },
    },
    linked_flag: {
        id: 7,
        team_id: 1,
        name: '',
        key: 'early-access-feature',
        filters: {
            groups: [
                {
                    variant: null,
                    properties: [],
                    rollout_percentage: undefined,
                },
            ],
            payloads: {},
            multivariate: null,
        },
        deleted: false,
        active: true,
        ensure_experience_continuity: false,
    },
    linked_flag_id: 7,
    targeting_flag: {
        id: 15,
        team_id: 1,
        name: 'Targeting flag for survey survey with release conditions',
        key: 'survey-targeting-survey-with-release-conditions',
        filters: {
            groups: [
                {
                    variant: null,
                    properties: [
                        {
                            key: 'email',
                            type: PropertyFilterType.Person,
                            value: ['li@posthog.com'],
                            operator: PropertyOperator.Exact,
                        },
                    ],
                    rollout_percentage: 100,
                },
            ],
            multivariate: null,
            payloads: {},
        },
        deleted: false,
        active: true,
        ensure_experience_continuity: false,
    },
    targeting_flag_filters: undefined,
    start_date: '2023-04-29T10:04:37.977401Z',
    end_date: null,
    archived: false,
    responses_limit: null,
    iteration_count: null,
    iteration_frequency_days: null,
    schedule: SurveySchedule.Once,
}

const MOCK_SURVEY_SHOWN = {
    clickhouse:
        "SELECT count() AS `survey shown` FROM events WHERE and(equals(events.team_id, 1), equals(events.event, %(hogql_val_0)s), ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', ''), %(hogql_val_2)s), 0)) LIMIT 100 SETTINGS readonly=2, max_execution_time=60",
    columns: ['survey shown'],
    hogql: "SELECT count() AS `survey shown` FROM events WHERE and(equals(event, 'survey shown'), equals(properties.$survey_id, '0188e637-3b72-0000-f407-07a338652af9')) LIMIT 100",
    query: "select count() as 'survey shown' from events where event == 'survey shown' and properties.$survey_id == '0187c279-bcae-0000-34f5-4f121921f006'",
    results: [[0]],
    types: [['survey shown', 'UInt64']],
}

const MOCK_SURVEY_RESULTS = {
    columns: ['*', 'properties.$survey_response', 'timestamp', 'person'],
    hasMore: false,
    results: [],
    types: [
        "Tuple(UUID, String, String, DateTime64(6, 'UTC'), Int64, String, String, DateTime64(6, 'UTC'))",
        'Nullable(String)',
        "DateTime64(6, 'UTC')",
        'String',
    ],
}

const MOCK_RESPONSES_COUNT = {
    '0187c279-bcae-0000-34f5-4f121921f005': 17,
    '0187c279-bcae-0000-34f5-4f121921f006': 25,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Surveys',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-06-28', // To stabilize relative dates
        pageUrl: urls.surveys(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/surveys/': toPaginatedResponse([
                    MOCK_BASIC_SURVEY,
                    MOCK_SURVEY_WITH_RELEASE_CONS,
                    MOCK_SURVEY_WITH_MULTIPLE_OPTIONS,
                ]),
                '/api/projects/:team_id/surveys/0187c279-bcae-0000-34f5-4f121921f005/': MOCK_BASIC_SURVEY,
                '/api/projects/:team_id/surveys/0187c279-bcae-0000-34f5-4f121921f006/': MOCK_SURVEY_WITH_RELEASE_CONS,
                '/api/projects/:team_id/surveys/998FE805-F9EF-4F25-A5D1-B9549C4E2143/':
                    MOCK_SURVEY_WITH_MULTIPLE_OPTIONS,
                '/api/projects/:team_id/surveys/responses_count/': MOCK_RESPONSES_COUNT,
                [`/api/projects/:team_id/feature_flags/${
                    (MOCK_SURVEY_WITH_RELEASE_CONS.linked_flag as FeatureFlagBasicType).id
                }`]: toPaginatedResponse([MOCK_SURVEY_WITH_RELEASE_CONS.linked_flag]),
                [`/api/projects/:team_id/feature_flags/${
                    (MOCK_SURVEY_WITH_RELEASE_CONS.targeting_flag as FeatureFlagBasicType).id
                }`]: toPaginatedResponse([MOCK_SURVEY_WITH_RELEASE_CONS.targeting_flag]),
            },
            post: {
                '/api/environments/:team_id/query/': async (req, res, ctx) => {
                    const body = await req.json()
                    if (body.kind == 'EventsQuery') {
                        return res(ctx.json(MOCK_SURVEY_RESULTS))
                    }
                    return res(ctx.json(MOCK_SURVEY_SHOWN))
                },
                // flag targeting has loaders, make sure they don't keep loading
                '/api/projects/:team_id/feature_flags/user_blast_radius/': () => [
                    200,
                    { users_affected: 120, total_users: 2000 },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const SurveysList: Story = {}

export const SurveysGlobalSettings: Story = {
    parameters: {
        pageUrl: urls.surveys(SurveysTabs.Settings),
    },
}

export const NewSurvey: Story = {
    parameters: {
        pageUrl: urls.survey('new'),
    },
}

export const NewSurveyCustomisationSection: StoryFn = () => {
    useDelayedOnMountEffect(() => {
        surveyLogic({ id: 'new' }).mount()
        surveyLogic({ id: 'new' }).actions.setSelectedSection(SurveyEditSection.Customization)
    })

    return <App />
}
NewSurveyCustomisationSection.parameters = { pageUrl: urls.survey('new') }

export const NewMultiQuestionSurveySection: StoryFn = () => {
    useDelayedOnMountEffect(() => {
        surveyLogic({ id: 'new' }).mount()
        surveyLogic({ id: 'new' }).actions.setSelectedSection(SurveyEditSection.Steps)
        surveyLogic({ id: 'new' }).actions.setSurveyValue('questions', [
            {
                type: SurveyQuestionType.MultipleChoice,
                question: "We're sorry to see you go. What's your reason for unsubscribing?",
                choices: [
                    'I no longer need the product',
                    'I found a better product',
                    'I found the product too difficult to use',
                    'Other',
                ],
            } as MultipleSurveyQuestion,
        ])
    })

    return <App />
}
NewMultiQuestionSurveySection.parameters = { pageUrl: urls.survey('new') }

export const NewSurveyPresentationSection: StoryFn = () => {
    useDelayedOnMountEffect(() => {
        surveyLogic({ id: 'new' }).mount()
        surveyLogic({ id: 'new' }).actions.setSelectedSection(SurveyEditSection.Presentation)
    })

    return <App />
}
NewSurveyPresentationSection.parameters = { pageUrl: urls.survey('new') }

export const NewSurveyTargetingSection: StoryFn = () => {
    useDelayedOnMountEffect(() => {
        surveyLogic({ id: 'new' }).mount()
        surveyLogic({ id: 'new' }).actions.setSelectedSection(SurveyEditSection.DisplayConditions)
        surveyLogic({ id: 'new' }).actions.setSurveyValue('conditions', { url: 'kiki' })
        surveyLogic({ id: 'new' }).actions.setSurveyValue('targeting_flag_filters', {
            groups: [
                {
                    properties: [{ key: '$browser', value: ['Chrome'], operator: 'exact', type: 'person' }],
                    rollout_percentage: 20,
                },
            ],
        })
    })

    return <App />
}
NewSurveyTargetingSection.parameters = {
    pageUrl: urls.survey('new?edit=true'),
    testOptions: {
        waitForSelector: ['.LemonBanner .LemonIcon', '.TaxonomicPropertyFilter__row'],
    },
}

export const NewSurveyAppearanceSection: StoryFn = () => {
    useDelayedOnMountEffect(() => {
        surveyLogic({ id: 'new' }).mount()
        surveyLogic({ id: 'new' }).actions.setSelectedSection(SurveyEditSection.Appearance)
    })

    return <App />
}
NewSurveyAppearanceSection.parameters = { pageUrl: urls.survey('new?edit=true') }

export const NewSurveyWithHTMLQuestionDescription: StoryFn = () => {
    useStorybookMocks({
        get: {
            // TODO: setting available featues should be a decorator to make this easy
            '/api/users/@me': () => [
                200,
                {
                    email: 'test@posthog.com',
                    first_name: 'Test Hedgehog',
                    organization: {
                        ...organizationCurrent,
                        available_product_features: [
                            {
                                key: 'surveys_text_html',
                                name: 'surveys_text_html',
                            },
                        ],
                    },
                },
            ],
        },
    })

    useDelayedOnMountEffect(() => {
        surveyLogic({ id: 'new' }).mount()
        surveyLogic({ id: 'new' }).actions.setSelectedSection(SurveyEditSection.Steps)
        surveyLogic({ id: 'new' }).actions.setSurveyValue('questions', [
            {
                type: SurveyQuestionType.Open,
                question: 'What is your favorite color?',
                description: '<strong>This description has HTML in it</strong>',
                descriptionContentType: 'html',
            },
        ])
    })

    return <App />
}
NewSurveyWithHTMLQuestionDescription.parameters = {
    pageUrl: urls.survey('new?edit=true'),
    testOptions: {
        waitForSelector: '.survey-question-description strong',
    },
}

export const NewSurveyWithTextQuestionDescriptionThatDoesNotRenderHTML: StoryFn = () => {
    useDelayedOnMountEffect(() => {
        surveyLogic({ id: 'new' }).mount()
        surveyLogic({ id: 'new' }).actions.setSelectedSection(SurveyEditSection.Steps)
        surveyLogic({ id: 'new' }).actions.setSurveyValue('questions', [
            {
                type: SurveyQuestionType.Open,
                question: 'What is your favorite color?',
                description: '<strong>This description has HTML in it</strong>',
                descriptionContentType: 'text',
            },
        ])
    })

    return <App />
}

NewSurveyWithTextQuestionDescriptionThatDoesNotRenderHTML.parameters = {
    pageUrl: urls.survey('new?edit=true'),
    testOptions: {
        waitForSelector: '.survey-question-description',
    },
}

export const SurveyView: Story = {
    tags: ['test-skip'], // FIXME: Fix the mocked data so that survey results can actually load
    parameters: {
        pageUrl: urls.survey(MOCK_SURVEY_WITH_RELEASE_CONS.id),
    },
}

export const SurveyTemplates: Story = {
    parameters: {
        pageUrl: urls.surveyTemplates(),
    },
}

export const SurveyNotFound: Story = {
    parameters: {
        pageUrl: urls.survey('1234566789'),
    },
}
