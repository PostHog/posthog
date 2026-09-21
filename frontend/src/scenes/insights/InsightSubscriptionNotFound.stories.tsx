import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { InsightSubscriptionNotFound } from './InsightSubscriptionNotFound'

const meta: Meta<typeof InsightSubscriptionNotFound> = {
    title: 'Scenes-App/Insights/Subscription insight not found',
    component: InsightSubscriptionNotFound,
    args: { insightShortId: 'missing1', subscriptionId: 123 },
    render: (args) => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/subscriptions/123/': {
                    id: 123,
                    insight_short_id: 'missing1',
                    deleted: false,
                },
            },
        })
        return <InsightSubscriptionNotFound {...args} />
    },
}
export default meta

type Story = StoryObj<typeof meta>

export const ExistingSubscription: Story = {}
