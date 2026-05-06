import { Meta, StoryObj } from '@storybook/react'

import {
    MOCK_SUBSCRIPTION_DASHBOARD_MANY_DESTINATIONS,
    MOCK_SUBSCRIPTION_INSIGHT_MANY_DESTINATIONS,
} from './subscriptionStoryFixtures'
import { SubscriptionSummary } from './SubscriptionSummary'

const meta: Meta<typeof SubscriptionSummary> = {
    component: SubscriptionSummary,
    title: 'Scenes-App/Subscriptions/Subscription summary',
    parameters: {
        mockDate: '2026-04-07',
    },
}

export default meta

type Story = StoryObj<typeof SubscriptionSummary>

/** Label is the resource kind; value is always the resource name (many destinations only affect Destination). */
export const InsightManyDestinations: Story = {
    args: {
        sub: MOCK_SUBSCRIPTION_INSIGHT_MANY_DESTINATIONS,
    },
}

export const DashboardManyDestinations: Story = {
    args: {
        sub: MOCK_SUBSCRIPTION_DASHBOARD_MANY_DESTINATIONS,
    },
}
