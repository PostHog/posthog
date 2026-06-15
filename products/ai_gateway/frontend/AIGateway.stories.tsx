import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const GATEWAYS = [
    {
        id: '0190a000-0000-7000-8000-000000000001',
        slug: 'default',
        created_at: '2024-07-01T10:00:00Z',
        updated_at: null,
        created_by: { id: 1, first_name: 'Bob', email: 'bob@posthog.com' },
    },
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/AIGateway',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-07-09',
        pageUrl: urls.aiGateway(),
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/gateways/': () => [200, { count: GATEWAYS.length, results: GATEWAYS }],
            },
            post: {
                'api/environments/:team_id/query/': () => [
                    200,
                    {
                        results: [[128, 45000, 90000, 12.34]],
                        columns: ['requests', 'input_tokens', 'output_tokens', 'cost_usd'],
                    },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const ListPage: Story = {}

export const Empty: Story = {
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/gateways/': () => [200, { count: 0, results: [] }],
            },
        }),
    ],
}
