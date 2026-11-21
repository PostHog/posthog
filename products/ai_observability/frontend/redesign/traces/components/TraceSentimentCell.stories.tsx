import type { Meta, StoryObj } from '@storybook/react'

import { TraceSentimentCell } from './TraceSentimentCell'

const meta: Meta<typeof TraceSentimentCell> = {
    title: 'Scenes-App/AI observability/Traces/Trace sentiment cell',
    component: TraceSentimentCell,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { sentiment: { label: 'positive', score: 0.82 }, status: 'ready' },
}
export default meta

type Story = StoryObj<typeof TraceSentimentCell>

export const Positive: Story = {}

export const Neutral: Story = { args: { sentiment: { label: 'neutral', score: 0.64 } } }

export const Negative: Story = { args: { sentiment: { label: 'negative', score: 0.71 } } }

export const Loading: Story = { args: { status: 'loading' } }

export const Failed: Story = { args: { status: 'error' } }

export const NoSentiment: Story = { args: { sentiment: null } }

export const NarrowContainer: Story = {
    decorators: [
        (StoryComponent) => (
            <div className="w-16">
                <StoryComponent />
            </div>
        ),
    ],
}
