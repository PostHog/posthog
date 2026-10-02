import { Meta, StoryObj } from '@storybook/react'

import { DailyVolumeChart } from './DailyVolumeChart'

const meta: Meta<typeof DailyVolumeChart> = {
    title: 'Products/Autoresearch/Daily volume chart',
    component: DailyVolumeChart,
    tags: ['autodocs'],
}
export default meta
type Story = StoryObj<typeof DailyVolumeChart>

const USERS_PER_DAY = [110, 118, 0, 121, 125, 131, 129, 140, 138, 152, 149, 160, 158, 171]

export const TwoWeeks: Story = {
    args: {
        points: USERS_PER_DAY.map((users, i) => ({
            day: `2026-08-${String(i + 1).padStart(2, '0')}`,
            users,
            avgProbabilityPct: 12 + (i % 5),
        })),
    },
}

export const SparseDays: Story = {
    args: {
        points: [
            { day: '2026-06-20', users: 72, avgProbabilityPct: 14.2 },
            { day: '2026-06-25', users: 77, avgProbabilityPct: 15.8 },
        ],
    },
}
