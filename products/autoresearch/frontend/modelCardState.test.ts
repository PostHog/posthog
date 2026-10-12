import { AutoresearchPipelineApi } from './generated/api.schemas'
import { modelCardState } from './modelCardState'

describe('modelCardState', () => {
    const liveRun: AutoresearchPipelineApi['live_training_run'] = {
        id: 'run-1',
        iteration_budget: 8,
        experiment_count: 2,
        best_holdout_score: 0.72,
        latest_agent_description: 'baseline',
    }

    test.each([
        { status: 'draft' as const, live: false, expected: 'draft' },
        { status: 'draft' as const, live: true, expected: 'training' },
        { status: 'bootstrapping' as const, live: false, expected: 'training' },
        { status: 'running' as const, live: true, expected: 'training' },
        { status: 'running' as const, live: false, expected: 'scored' },
        { status: 'paused' as const, live: false, expected: 'scored' },
    ])('$status with a live run: $live is $expected', ({ status, live, expected }) => {
        expect(modelCardState({ status, live_training_run: live ? liveRun : null })).toEqual(expected)
    })
})
