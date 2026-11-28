import type { Meta, StoryObj } from '@storybook/react'

import { TraceNameCell } from './TraceNameCell'

const meta: Meta<typeof TraceNameCell> = {
    title: 'Scenes-App/AI observability/Traces/Trace name cell',
    component: TraceNameCell,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { name: 'answer-billing-question', href: '/ai-observability/traces/trace-1', isSupportTrace: false },
}
export default meta

type Story = StoryObj<typeof TraceNameCell>

export const Named: Story = {}

export const Untitled: Story = { args: { name: null } }

export const SupportTrace: Story = { args: { isSupportTrace: true } }

export const NarrowContainer: Story = {
    args: { name: 'summarize-the-customer-conversation-before-handoff', isSupportTrace: true },
    decorators: [
        (StoryComponent) => (
            <div className="w-40">
                <StoryComponent />
            </div>
        ),
    ],
}
