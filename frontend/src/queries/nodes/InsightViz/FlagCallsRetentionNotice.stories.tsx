import type { Meta, StoryObj } from '@storybook/react'

import { FlagCallsRetentionNotice } from './FlagCallsRetentionNotice'

const meta: Meta<typeof FlagCallsRetentionNotice> = {
    title: 'Scenes-App/Insights/Flag calls retention notice',
    component: FlagCallsRetentionNotice,
    parameters: {
        mockDate: '2026-10-07',
    },
}
export default meta

type Story = StoryObj<typeof FlagCallsRetentionNotice>

export const Default: Story = {}
