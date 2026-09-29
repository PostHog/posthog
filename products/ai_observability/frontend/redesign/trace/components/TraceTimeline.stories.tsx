import type { Meta, StoryObj } from '@storybook/react'

import { openaiAgentsWithEvals } from '../sampleFixtures/openaiAgentsWithEvals'
import { FIXTURE_TIMELINE_ROWS, withWidth } from '../storyFixtures'
import { TraceTimeline } from './TraceTimeline'

const meta: Meta<typeof TraceTimeline> = {
    title: 'Scenes-App/AI observability/Trace view/Trace timeline',
    component: TraceTimeline,
    args: { rows: FIXTURE_TIMELINE_ROWS, totalMs: 2310, selectedNodeId: 'gen-answer', onSelectNode: () => {} },
}
export default meta

type Story = StoryObj<typeof TraceTimeline>

export const Default: Story = {}
export const AgentRun: Story = {
    args: { ...openaiAgentsWithEvals.timeline, selectedNodeId: openaiAgentsWithEvals.initialNodeId },
}
export const Empty: Story = { args: { rows: [] } }
export const UnknownLatency: Story = {
    args: {
        rows: [
            ...FIXTURE_TIMELINE_ROWS,
            { id: 'span-feedback', kind: 'span', name: 'record-feedback', depth: 1, startMs: 1500, durationMs: null },
        ],
    },
}
export const Narrow: Story = { decorators: [withWidth(520)] }
