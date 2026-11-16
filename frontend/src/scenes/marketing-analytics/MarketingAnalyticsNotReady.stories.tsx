import type { Meta, StoryObj } from '@storybook/react'

import { MarketingAnalyticsNotReady } from './MarketingAnalyticsNotReady'

type Story = StoryObj<typeof MarketingAnalyticsNotReady>
const meta: Meta<typeof MarketingAnalyticsNotReady> = {
    title: 'Scenes-App/Marketing Analytics/Not ready',
    component: MarketingAnalyticsNotReady,
    tags: ['autodocs'],
}
export default meta

export const AutoRefreshing: Story = { args: { autoRefreshing: true } }

export const GaveUp: Story = { args: { autoRefreshing: false } }
