import type { Meta, StoryObj } from '@storybook/react'

import { MarketingAnalyticsFreshness } from './MarketingAnalyticsFreshness'

type Story = StoryObj<typeof MarketingAnalyticsFreshness>
const meta: Meta<typeof MarketingAnalyticsFreshness> = {
    title: 'Scenes-App/Marketing Analytics/Freshness',
    component: MarketingAnalyticsFreshness,
    tags: ['autodocs'],
    parameters: { mockDate: '2025-02-15T12:00:00Z' },
}
export default meta

export const Computed: Story = { args: { latestDayComputedAt: '2025-02-15T11:40:00Z' } }

// No latest-day stamp known: renders nothing, so there is nothing to snapshot.
export const Unknown: Story = { args: { latestDayComputedAt: null }, tags: ['test-skip'] }
