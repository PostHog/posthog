import type { Meta, StoryObj } from '@storybook/react'

import { EvaluationRun } from '../evaluations/types'
import { EvaluationRunTimestampCell } from './EvaluationRunTimestampCell'

const meta: Meta<typeof EvaluationRunTimestampCell> = {
    title: 'Scenes-App/LLM observability/EvaluationRunTimestampCell',
    component: EvaluationRunTimestampCell,
    parameters: { layout: 'padded', mockDate: '2026-09-29T12:00:00Z' },
}
export default meta

type Story = StoryObj<typeof EvaluationRunTimestampCell>

const run: EvaluationRun = {
    id: 'run-1',
    evaluation_id: 'evaluation-1',
    evaluation_name: 'Valid HogQL',
    generation_id: 'generation-1',
    trace_id: 'trace-1',
    timestamp: '2026-09-28T10:44:00Z',
    result: true,
    reasoning: '',
    status: 'completed',
}

export const LiveAndBackfill: Story = {
    render: () => (
        <div className="flex flex-col gap-4">
            <div className="space-y-2">
                <div>Live result</div>
                <EvaluationRunTimestampCell run={run} />
            </div>
            <div className="space-y-2">
                <div>Result from a backfill</div>
                <EvaluationRunTimestampCell run={{ ...run, id: 'run-2', backfill_id: 'backfill-1' }} />
            </div>
        </div>
    ),
}
