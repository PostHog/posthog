import type { Meta, StoryObj } from '@storybook/react'

import { TraceSearchBox } from './TraceSearchBox'

const meta: Meta<typeof TraceSearchBox> = {
    title: 'Scenes-App/AI observability/Trace view/Trace search box',
    component: TraceSearchBox,
    args: {
        query: 'invoice',
        status: 'ready',
        total: 7,
        matchingSteps: 3,
        position: null,
        failure: null,
        onQueryChange: () => {},
        onStep: () => {},
    },
}
export default meta

type Story = StoryObj<typeof TraceSearchBox>

export const Idle: Story = { args: { query: '', status: 'idle', total: 0, matchingSteps: 0 } }
export const Searching: Story = {
    args: { status: 'loading', total: 0, matchingSteps: 0 },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const Matches: Story = {}
export const MatchSelected: Story = { args: { position: 2 } }
export const NoMatches: Story = { args: { query: 'refund', total: 0, matchingSteps: 0 } }
export const TooSlow: Story = { args: { status: 'error', failure: 'too_slow', total: 0, matchingSteps: 0 } }
export const Failed: Story = { args: { status: 'error', failure: 'failed', total: 0, matchingSteps: 0 } }
