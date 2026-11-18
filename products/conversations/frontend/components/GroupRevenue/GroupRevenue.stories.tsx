import type { Meta, StoryObj } from '@storybook/react'

import { GroupRevenue } from './GroupRevenue'

const meta: Meta<typeof GroupRevenue> = {
    title: 'Scenes-App/Support/GroupRevenue',
    component: GroupRevenue,
    parameters: { layout: 'padded', viewMode: 'story' },
    decorators: [
        (Story) => (
            <div className="w-[300px]">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof GroupRevenue>

export const FromRevenueAnalytics: Story = {
    args: {
        revenue: {
            mrr: { value: 1250, source: 'revenue-analytics' },
            lifetimeValue: { value: 1234567.89, source: 'revenue-analytics' },
        },
    },
}

export const OnlyMrrFromGroupProperties: Story = {
    args: {
        revenue: {
            mrr: { value: 99, source: 'properties' },
            lifetimeValue: { value: null, source: null },
        },
    },
}
