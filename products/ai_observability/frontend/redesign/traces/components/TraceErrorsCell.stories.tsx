import type { Meta, StoryObj } from '@storybook/react'

import { TraceErrorsCell } from './TraceErrorsCell'

const meta: Meta<typeof TraceErrorsCell> = {
    title: 'Scenes-App/AI observability/Traces/Trace errors cell',
    component: TraceErrorsCell,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { firstError: 'Rate limit reached for requests', errorCount: 1, hasError: true },
}
export default meta

type Story = StoryObj<typeof TraceErrorsCell>

export const OneError: Story = {}

export const SeveralErrors: Story = { args: { errorCount: 4 } }

export const ErrorWithoutText: Story = { args: { firstError: null, errorCount: 2 } }

export const NarrowContainer: Story = {
    args: {
        firstError: 'Context window exceeded: the prompt has 140,000 tokens and the model accepts 128,000',
        errorCount: 3,
    },
    decorators: [
        (StoryComponent) => (
            <div className="w-40">
                <StoryComponent />
            </div>
        ),
    ],
}
