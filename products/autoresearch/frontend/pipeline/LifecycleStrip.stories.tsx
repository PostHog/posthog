import { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { LifecycleInput, pipelineLifecycle } from '../pipelineLifecycle'
import { LifecycleStrip } from './LifecycleStrip'

const NOW = dayjs('2026-03-01T12:00:00Z')

const NEW_PIPELINE: LifecycleInput['pipeline'] = {
    created_at: '2026-01-01T00:00:00Z',
    horizon_days: 7,
    last_scored_at: null,
    training_run_count: 0,
    experiment_count: 0,
    live_training_run: null,
}

const SCORED_PIPELINE: LifecycleInput['pipeline'] = {
    ...NEW_PIPELINE,
    training_run_count: 2,
    experiment_count: 14,
    last_scored_at: '2026-03-01T03:00:00Z',
}

function scoringRun(day: string): LifecycleInput['runs'][number] {
    return { run_type: 'inference', status: 'completed', created_at: `${day}T03:00:00Z`, rows_scored: 100, metrics: {} }
}

function steps(overrides: Partial<LifecycleInput>): ReturnType<typeof pipelineLifecycle> {
    return pipelineLifecycle({
        pipeline: NEW_PIPELINE,
        champion: null,
        runs: [],
        validatedDates: [],
        now: NOW,
        ...overrides,
    })
}

// Each story builds its steps in render, so relative times read the pinned story clock.
const meta: Meta<typeof LifecycleStrip> = {
    title: 'Products/Autoresearch/Lifecycle strip',
    component: LifecycleStrip,
    parameters: { mockDate: '2026-03-01T12:00:00Z' },
}
export default meta
type Story = StoryObj<typeof LifecycleStrip>

export const Draft: Story = {
    render: () => <LifecycleStrip steps={steps({})} />,
}

export const FirstTrainingRun: Story = {
    render: () => (
        <LifecycleStrip
            steps={steps({
                pipeline: { ...NEW_PIPELINE, training_run_count: 1, experiment_count: 3, live_training_run: {} },
            })}
        />
    ),
}

export const PreliminaryChampion: Story = {
    render: () => (
        <LifecycleStrip
            steps={steps({
                pipeline: SCORED_PIPELINE,
                champion: { is_preliminary: true, promoted_at: '2026-02-27T00:00:00Z' },
                runs: [scoringRun('2026-03-01')],
            })}
        />
    ),
}

export const ValidatedChampion: Story = {
    render: () => (
        <LifecycleStrip
            steps={steps({
                pipeline: SCORED_PIPELINE,
                champion: { is_preliminary: false, promoted_at: '2026-01-10T00:00:00Z' },
                runs: [scoringRun('2026-02-10'), scoringRun('2026-02-11'), scoringRun('2026-03-01')],
                validatedDates: ['2026-02-10', '2026-02-11'],
            })}
        />
    ),
}
