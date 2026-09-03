import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { MarketingAnalyticsFreshness } from './MarketingAnalyticsFreshness'

type Story = StoryObj<typeof MarketingAnalyticsFreshness>
const meta: Meta<typeof MarketingAnalyticsFreshness> = {
    title: 'Scenes-App/Marketing Analytics/Freshness',
    component: MarketingAnalyticsFreshness,
    tags: ['autodocs'],
}
export default meta

// Within the ~2h refresh window: neutral clock badge.
export const Fresh: Story = { args: { computedAt: dayjs().subtract(20, 'minute').toISOString() } }

// Older than the refresh window (warmer behind): warning badge.
export const Behind: Story = { args: { computedAt: dayjs().subtract(5, 'hour').toISOString() } }

// No precompute freshness known: renders nothing.
export const Unknown: Story = { args: { computedAt: null } }
