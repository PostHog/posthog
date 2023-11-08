import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'
import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import { PropertyFilterType, PropertyOperator, Survey, SurveyQuestionType, SurveyType } from '~/types'
import { Meta } from '@storybook/react'
import { router } from 'kea-router'
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
    conditions: { url: 'posthog', selector: '' },
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
                    rollout_percentage: null,
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
}

// const MOCK_SURVEY_DISMISSED = {
//     "clickhouse": "SELECT count() AS `survey dismissed` FROM events WHERE and(equals(events.team_id, 1), equals(events.event, %(hogql_val_0)s), equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', ''), %(hogql_val_2)s)) LIMIT 100 SETTINGS readonly=2, max_execution_time=60",
//     "columns": [
//         "survey dismissed"
//     ],
//     "hogql": "SELECT count() AS `survey dismissed` FROM events WHERE and(equals(event, 'survey dismissed'), equals(properties.$survey_id, '0188e637-3b72-0000-f407-07a338652af9')) LIMIT 100",
//     "query": "select count() as 'survey dismissed' from events where event == 'survey dismissed' and properties.$survey_id == '0188e637-3b72-0000-f407-07a338652af9'",
//     "results": [
//         [
//             0
//         ]
//     ],
//     "types": [
//         [
//             "survey dismissed",
//             "UInt64"
//         ]
//     ]
// }

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
    title: 'Scenes-App/Surveys',
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            excludeNavigationFromSnapshot: true,
        },
        viewMode: 'story',
        mockDate: '2023-06-28', // To stabilize relative dates
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/surveys/': toPaginatedResponse([
                    MOCK_BASIC_SURVEY,
                    MOCK_SURVEY_WITH_RELEASE_CONS,
                ]),
                '/api/projects/:team_id/surveys/0187c279-bcae-0000-34f5-4f121921f005/': MOCK_BASIC_SURVEY,
                '/api/projects/:team_id/surveys/0187c279-bcae-0000-34f5-4f121921f006/': MOCK_SURVEY_WITH_RELEASE_CONS,
                '/api/projects/:team_id/surveys/responses_count/': MOCK_RESPONSES_COUNT,
            },
            post: {
                '/api/projects/:team_id/query/': (req) => {
                    if ((req.body as any).kind == 'EventsQuery') {
                        return MOCK_SURVEY_RESULTS
                    }
                    return MOCK_SURVEY_SHOWN
                },
            },
        }),
    ],
}
export default meta
export function SurveysList(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.surveys())
    }, [])
    return <App />
}

export function NewSurvey(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.survey('new'))
    }, [])
    return <App />
}

export function NewSurveyCustomisationSection(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.survey('new'))
        surveyLogic({ id: 'new' }).mount()
        surveyLogic({ id: 'new' }).actions.setSelectedSection(SurveyEditSection.Customization)
    }, [])
    return <App />
}

export function NewSurveyPresentationSection(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.survey('new'))
        surveyLogic({ id: 'new' }).mount()
        surveyLogic({ id: 'new' }).actions.setSelectedSection(SurveyEditSection.Presentation)
    }, [])
    return <App />
}

export function NewSurveyTargetingSection(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.survey('new'))
        surveyLogic({ id: 'new' }).mount()
        surveyLogic({ id: 'new' }).actions.setSelectedSection(SurveyEditSection.Targeting)
        surveyLogic({ id: 'new' }).actions.setSurveyValue('conditions', { url: 'kiki' })
        surveyLogic({ id: 'new' }).actions.setSurveyValue('targeting_flag_filters', {
            groups: [
                {
                    properties: [{ key: '$browser', value: ['Chrome'], operator: 'exact', type: 'person' }],
                    rollout_percentage: 20,
                },
            ],
        })
    }, [])
    return <App />
}

export function NewSurveyAppearanceSection(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.survey('new'))
        surveyLogic({ id: 'new' }).mount()
        surveyLogic({ id: 'new' }).actions.setSelectedSection(SurveyEditSection.Appearance)
    }, [])
    return <App />
}

export function SurveyView(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.survey(MOCK_SURVEY_WITH_RELEASE_CONS.id))
    }, [])
    return <App />
}

export function SurveyTemplates(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.surveyTemplates())
    }, [])
    return <App />
}

export function SurveyNotFound(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.survey('1234566789'))
    }, [])
    return <App />
}
