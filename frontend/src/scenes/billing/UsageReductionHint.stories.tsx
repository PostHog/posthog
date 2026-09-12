import { Meta, StoryObj } from '@storybook/react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { buildUsageReductionOptions } from './billing-utils'
import { UsageReductionHint } from './UsageReductionHint'

const meta: Meta<typeof UsageReductionHint> = {
    title: 'Scenes-Other/Billing/UsageReductionHint',
    component: UsageReductionHint,
    parameters: { layout: 'padded' },
    decorators: [
        (Story) => (
            <div className="w-[720px]">
                <LemonBanner type="error">
                    <b>Usage limit reached</b>
                    <br />
                    You have reached the usage limit for Session replay. Please increase your billing limit or data loss
                    may occur.
                    <br />
                    <Story />
                </LemonBanner>
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof UsageReductionHint>

export const ProductWithItsOwnLever: Story = {
    args: { options: buildUsageReductionOptions([{ type: 'session_replay' }]) },
}

/** Every other product falls back to the cost docs. */
export const ProductWithoutOne: Story = {
    args: { options: buildUsageReductionOptions([{ type: 'data_warehouse' }]) },
}
