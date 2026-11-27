import type { Meta, StoryObj } from '@storybook/react'

import { FlagCallsRetentionNotice } from './FlagCallsRetentionNotice'

const meta: Meta<typeof FlagCallsRetentionNotice> = {
    title: 'Scenes-App/Insights/Flag calls retention notice',
    component: FlagCallsRetentionNotice,
    decorators: [
        // LemonBanner is a size container, so a shrink-to-fit snapshot root collapses it to its padding.
        (Story) => (
            <div className="w-[32rem]">
                <Story />
            </div>
        ),
    ],
    parameters: {
        mockDate: '2026-10-07',
    },
}
export default meta

type Story = StoryObj<typeof FlagCallsRetentionNotice>

export const Default: Story = { args: { gap: 'periods', retentionStartDate: '2026-07-09' } }

export const FirstPeriod: Story = { args: { gap: 'first-period', retentionStartDate: '2026-07-09' } }
