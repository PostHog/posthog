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

// Within the ~2h refresh window: neutral clock badge.
export const Fresh: Story = { args: { computedAt: '2025-02-15T11:40:00Z' } }

// Older than the refresh window (warmer behind): warning badge.
export const Behind: Story = { args: { computedAt: '2025-02-15T07:00:00Z' } }

// No precompute freshness known: renders nothing, so there is nothing to snapshot.
export const Unknown: Story = { args: { computedAt: null }, tags: ['test-skip'] }
