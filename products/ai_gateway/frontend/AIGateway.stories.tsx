import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

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
export const Page: Story = {}
