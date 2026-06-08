import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const GATEWAY = {
    id: '0190a000-0000-7000-8000-000000000001',
    slug: 'default',
    created_at: '2024-07-01T10:00:00Z',
    updated_at: null,
    created_by: { id: 1, first_name: 'Bob', email: 'bob@posthog.com' },
    bound_credentials_count: 1,
}

const BOUND_CREDENTIALS = {
    personal_api_keys: [
        {
            id: 'k1',
            label: 'Reports bot',
            user: { id: 1, first_name: 'Bob', email: 'bob@posthog.com' },
            last_used_at: '2024-07-08T09:00:00Z',
        },
    ],
    oauth_applications: [],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/AIGatewayDetail',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-07-09',
        pageUrl: urls.aiGatewayDetail(GATEWAY.id),
    },
    decorators: [
        mswDecorator({
            get: {
                // Literal path before :id/ so it isn't shadowed by the gateway-detail handler.
                'api/projects/:team_id/gateways/assignable_credentials/': () => [
                    200,
                    [{ id: 'pak_unassigned', label: 'local dev key', last_used_at: null }],
                ],
                'api/projects/:team_id/gateways/': () => [200, { count: 1, results: [GATEWAY] }],
                'api/projects/:team_id/gateways/:id/': () => [200, GATEWAY],
                'api/projects/:team_id/gateways/:id/credentials/': () => [200, BOUND_CREDENTIALS],
            },
            post: {
                'api/environments/:team_id/query/': () => [
                    200,
                    {
                        results: [[42, 1200, 3400, 5.67]],
                        columns: ['requests', 'input_tokens', 'output_tokens', 'cost_usd'],
                    },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const Detail: Story = {}
