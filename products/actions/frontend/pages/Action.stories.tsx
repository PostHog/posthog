import { MOCK_DEFAULT_BASIC_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import { AccessControlLevel, ActionType } from '~/types'

const MOCK_ACTION: ActionType = {
    id: 1,
    name: 'Test Action',
    description: '',
    tags: [],
    post_to_slack: false,
    slack_message_format: '',
    steps: [
        {
            event: '$pageview',
            selector: null,
            text: null,
            text_matching: null,
            href: null,
            href_matching: 'contains',
            url: 'posthog.com/pricing',
            url_matching: 'contains',
        },
        {
            event: '$autocapture',
            selector: null,
            text: 'this text',
            text_matching: null,
            href: null,
            href_matching: 'contains',
            url: null,
            url_matching: 'contains',
        },
        {
            event: '$screen',
            properties: [
                {
                    key: '$screen_name',
                    value: 'HomeScreen',
                    operator: 'exact',
                    type: 'event',
                },
            ] as any,
            selector: null,
            text: null,
            text_matching: null,
            href: null,
            href_matching: 'contains',
            url: null,
            url_matching: null,
        },
        {
            event: '$identify',
            properties: [
                {
                    key: '$browser',
                    value: ['Chrome'],
                    operator: 'exact',
                    type: 'person',
                },
            ] as any,
            selector: null,
            text: null,
            text_matching: null,
            href: null,
            href_matching: 'contains',
            url: null,
            url_matching: 'contains',
        },
    ],
    created_at: '2024-05-21T12:57:50.907581Z',
    created_by: MOCK_DEFAULT_BASIC_USER,
    deleted: false,
    is_calculating: false,
    last_calculated_at: '2024-05-21T12:57:50.894221Z',
    pinned_at: null,
    user_access_level: AccessControlLevel.Editor,
    reference_count: 3,
}

const MOCK_SCREEN_ACTION: ActionType = {
    id: 2,
    name: 'Mobile Screen Views',
    description: 'Tracks key screen views in the mobile app',
    tags: ['mobile'],
    post_to_slack: false,
    slack_message_format: '',
    steps: [
        {
            event: '$screen',
            properties: [
                {
                    key: '$screen_name',
                    value: 'HomeScreen',
                    operator: 'exact',
                    type: 'event',
                },
            ] as any,
            selector: null,
            text: null,
            text_matching: null,
            href: null,
            href_matching: 'contains',
            url: null,
            url_matching: null,
        },
        {
            event: '$screen',
            properties: [
                {
                    key: '$screen_name',
                    value: 'Settings',
                    operator: 'icontains',
                    type: 'event',
                },
            ] as any,
            selector: null,
            text: null,
            text_matching: null,
            href: null,
            href_matching: 'contains',
            url: null,
            url_matching: null,
        },
    ],
    created_at: '2024-05-21T12:57:50.907581Z',
    created_by: MOCK_DEFAULT_BASIC_USER,
    deleted: false,
    is_calculating: false,
    last_calculated_at: '2024-05-21T12:57:50.894221Z',
    pinned_at: null,
    user_access_level: AccessControlLevel.Editor,
    reference_count: 0,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Management/Actions',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-15', // To stabilize relative dates
        pageUrl: urls.actions(),
        testOptions: { viewport: { width: 1300, height: 2000 } },
    },
    decorators: [
        mswDecorator({
            get: {
                // Every event these actions point at is arriving, so no step carries a health warning.
                '/api/projects/:team_id/event_definitions/': ({ request }) =>
                    toPaginatedResponse(
                        new URL(request.url).searchParams
                            .getAll('names')
                            .map((name, index) => ({ id: `${index}`, name, last_seen_at: '2023-02-14T10:00:00Z' }))
                    ),
                '/api/projects/:team_id/actions/': toPaginatedResponse([MOCK_ACTION, MOCK_SCREEN_ACTION]),
                '/api/projects/:team_id/actions/1/': MOCK_ACTION,
                '/api/projects/:team_id/actions/2/': MOCK_SCREEN_ACTION,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const ActionsList: Story = {}

export const Action: Story = {
    parameters: {
        pageUrl: urls.action(MOCK_ACTION.id),
    },
}

export const ScreenAction: Story = {
    parameters: {
        pageUrl: urls.action(MOCK_SCREEN_ACTION.id),
    },
}

export const NewAction: Story = {
    parameters: {
        pageUrl: urls.createAction(),
    },
}

const unhealthyEventsDecorator = mswDecorator({
    get: {
        // `$pageview` stopped arriving months ago and `$autocapture` has no definition at all.
        '/api/projects/:team_id/event_definitions/': toPaginatedResponse([
            { id: '1', name: '$pageview', last_seen_at: '2022-11-01T10:00:00Z' },
            { id: '2', name: '$screen', last_seen_at: '2023-02-14T10:00:00Z' },
            { id: '3', name: '$identify', last_seen_at: '2023-02-14T10:00:00Z' },
        ]),
    },
})

export const ActionsListWithUnhealthyEvents: Story = {
    decorators: [unhealthyEventsDecorator],
}

export const ActionWithUnhealthyEvents: Story = {
    parameters: {
        pageUrl: urls.action(MOCK_ACTION.id),
    },
    decorators: [unhealthyEventsDecorator],
}
