import type { Meta, StoryObj } from '@storybook/react'

import { TracePreviewCell } from './TracePreviewCell'

const meta: Meta<typeof TracePreviewCell> = {
    title: 'Scenes-App/AI observability/Traces/Trace preview cell',
    component: TracePreviewCell,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { text: 'Why was I charged twice this month?', missingReason: null, status: 'ready' },
}
export default meta

type Story = StoryObj<typeof TracePreviewCell>

export const Preview: Story = {}

export const Loading: Story = { args: { status: 'loading' } }

export const Failed: Story = { args: { status: 'error' } }

export const NoPreview: Story = { args: { text: null } }

export const TooLarge: Story = { args: { text: null, missingReason: 'too_large' } }

export const TimedOut: Story = { args: { text: null, missingReason: 'timed_out' } }

export const NarrowContainer: Story = {
    args: {
        text: 'Summarize the attached contract and list every clause that mentions termination, renewal or notice periods, with the page each one is on.',
    },
    decorators: [
        (StoryComponent) => (
            <div className="w-40">
                <StoryComponent />
            </div>
        ),
    ],
}
