import type { Meta, StoryObj } from '@storybook/react'

import { MarketingAnalyticsNotReady } from './MarketingAnalyticsNotReady'

type Story = StoryObj<typeof MarketingAnalyticsNotReady>
const meta: Meta<typeof MarketingAnalyticsNotReady> = {
    title: 'Scenes-App/Marketing Analytics/Not ready',
    component: MarketingAnalyticsNotReady,
    tags: ['autodocs'],
    decorators: [
        // LemonBanner is a CSS container, so it has no width of its own and needs a sized parent.
        (Story) => (
            <div className="w-160">
                <Story />
            </div>
        ),
    ],
}
export default meta

export const AutoRefreshing: Story = { args: { autoRefreshing: true } }

export const GaveUp: Story = { args: { autoRefreshing: false } }
