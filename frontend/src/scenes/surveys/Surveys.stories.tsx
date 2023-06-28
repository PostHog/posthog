import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'
import { mswDecorator, useFeatureFlags } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import { Survey, SurveyType } from '~/types'

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
    questions: [{ question: 'question 1?', type: 'open' }],
    conditions: null,
    linked_flag: null,
    linked_flag_id: null,
    targeting_flag: null,
    appearance: { backgroundColor: 'white', textColor: 'black', submitButtonColor: '#2C2C2C' },
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
    questions: [{ question: 'question 2?', type: 'open' }],
    appearance: null,
    conditions: { url: 'posthog' },
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
                            type: 'person',
                            value: ['li@posthog.com'],
                            operator: 'exact',
                        },
                    ],
                    rollout_percentage: 100,
                },
            ],
        },
        deleted: false,
        active: true,
        ensure_experience_continuity: false,
    },
    start_date: '2023-04-29T10:04:37.977401Z',
    end_date: null,
    archived: false,
}

export default {
    title: 'Scenes-App/Surveys',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
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
            },
        }),
    ],
} as Meta

export function SurveysList(): JSX.Element {
    useFeatureFlags([FEATURE_FLAGS.SURVEYS])
    useEffect(() => {
        router.actions.push(urls.surveys())
    }, [])
    return <App />
}

export function NewSurvey(): JSX.Element {
    useFeatureFlags([FEATURE_FLAGS.SURVEYS])
    useEffect(() => {
        router.actions.push(urls.survey('new'))
    }, [])
    return <App />
}

export function SurveyView(): JSX.Element {
    useFeatureFlags([FEATURE_FLAGS.SURVEYS])
    useEffect(() => {
        router.actions.push(urls.survey(MOCK_SURVEY_WITH_RELEASE_CONS.id))
    }, [])
    return <App />
}
