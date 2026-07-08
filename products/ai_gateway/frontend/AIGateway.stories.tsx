import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

// The scene fires two HogQL queries (by-model breakdown, spend-by-day) at the same
// endpoint, so branch the mock on the query body to return the right shape for each.
const queryDecorator = (hasData: boolean): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        post: {
            'api/environments/:team_id/query/': async ({ request }) => {
                const body = (await request.json()) as { query?: { query?: string } }
                const hogql = String(body?.query?.query ?? '')
                if (hogql.includes('GROUP BY model')) {
                    return [
                        200,
                        {
                            results: hasData
                                ? [
                                      ['gpt-5-mini', 96, 60000, 41000, 9.1],
                                      ['claude-sonnet-4.6', 32, 20000, 14000, 3.24],
                                  ]
                                : [],
                            columns: ['model', 'requests', 'input_tokens', 'output_tokens', 'cost_usd'],
                        },
                    ]
                }
                return [
                    200,
                    {
                        results: hasData
                            ? [
                                  ['2024-07-01 00:00:00', 4.2],
                                  ['2024-07-05 00:00:00', 8.14],
                              ]
                            : [],
                        columns: ['day', 'cost_usd'],
                    },
                ]
            },
        },
    })

const meta: Meta = {
    component: App,
    title: 'Scenes-App/AIGateway',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-07-09',
        pageUrl: urls.aiGateway(),
        featureFlags: [FEATURE_FLAGS.AI_GATEWAY],
    },
}
export default meta

type Story = StoryObj<{}>

// Team with usage: metrics, spend trend, and per-model breakdown populated.
export const Page: Story = { decorators: [queryDecorator(true)] }

// Team that hasn't used the gateway yet: the same dashboard, all zeroed out.
export const Empty: Story = { decorators: [queryDecorator(false)] }
