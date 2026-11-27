import type { Meta, StoryObj } from '@storybook/react'

import { PartialTotal } from './PartialTotal'

const meta: Meta<typeof PartialTotal> = {
    title: 'Scenes-App/AI observability/Shared/Partial total',
    component: PartialTotal,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { children: '1,840 in · 212 out', partial: true },
}
export default meta

type Story = StoryObj<typeof PartialTotal>

export const Partial: Story = {}
export const Whole: Story = { args: { partial: false } }
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="border border-dashed border-primary" style={{ width: 120 }}>
                <Story />
            </div>
        ),
    ],
}
