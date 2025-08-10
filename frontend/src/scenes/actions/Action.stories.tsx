import { Meta, StoryObj } from '@storybook/react'
import { MOCK_DEFAULT_BASIC_USER } from 'lib/api.mock'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'
import { ActionType } from '~/types'

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
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Management/Actions',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-15', // To stabilize relative dates
        pageUrl: urls.actions(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/actions/': toPaginatedResponse([MOCK_ACTION]),
                '/api/projects/:team_id/actions/1/': MOCK_ACTION,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const ActionsList: Story = {}

export const Action: Story = {
    parameters: {
        pageUrl: urls.action(MOCK_ACTION.id),
    },
}
