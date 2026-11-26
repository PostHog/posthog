import type { Decorator, Meta, StoryObj } from '@storybook/react'

import { TurnSideMissingNotice } from './TurnSideMissingNotice'

// The notice aligns itself to a side of the thread, which is a flex column.
const inThread: Decorator = (StoryComponent, { parameters }) => (
    <div className="flex flex-col border border-dashed border-primary" style={{ width: parameters.threadWidth ?? 480 }}>
        <StoryComponent />
    </div>
)

const meta: Meta<typeof TurnSideMissingNotice> = {
    title: 'Scenes-App/AI observability/Trace view/Turn side missing notice',
    component: TurnSideMissingNotice,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { side: 'output', reason: 'too_large', partial: false, onOpenTrace: () => {} },
    decorators: [inThread],
}
export default meta

type Story = StoryObj<typeof TurnSideMissingNotice>

export const OutputTooLarge: Story = {}
export const OutputTimedOut: Story = { args: { reason: 'timed_out' } }
export const InputTooLarge: Story = { args: { side: 'input' } }
export const InputTimedOut: Story = { args: { side: 'input', reason: 'timed_out' } }
export const PartialOutput: Story = { args: { partial: true } }
export const PartialInput: Story = { args: { side: 'input', partial: true, reason: 'timed_out' } }
export const Narrow: Story = { parameters: { threadWidth: 200 } }
