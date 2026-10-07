import { dayjs } from 'lib/dayjs'

import { LifecycleInput, LifecycleStepState, pipelineLifecycle } from './pipelineLifecycle'

const NOW = dayjs('2026-03-01T12:00:00Z')

const NEW_PIPELINE: LifecycleInput['pipeline'] = {
    created_at: '2026-01-01T00:00:00Z',
    horizon_days: 7,
    last_scored_at: null,
    training_run_count: 0,
    experiment_count: 0,
    live_training_run: null,
}

function scoringRun(day: string): LifecycleInput['runs'][number] {
    return { run_type: 'inference', status: 'completed', created_at: `${day}T03:00:00Z` }
}

function input(overrides: Partial<LifecycleInput>): LifecycleInput {
    return { pipeline: NEW_PIPELINE, champion: null, runs: [], validatedDates: [], now: NOW, ...overrides }
}

describe('pipelineLifecycle', () => {
    it.each<[string, LifecycleInput, LifecycleStepState[]]>([
        ['a draft model', input({}), ['done', 'current', 'upcoming', 'upcoming', 'upcoming']],
        [
            'a model in its first training run',
            input({
                pipeline: { ...NEW_PIPELINE, training_run_count: 1, experiment_count: 3, live_training_run: {} },
            }),
            ['done', 'current', 'upcoming', 'upcoming', 'upcoming'],
        ],
        [
            'a preliminary champion that scored before any date matured',
            input({
                pipeline: {
                    ...NEW_PIPELINE,
                    training_run_count: 1,
                    experiment_count: 5,
                    last_scored_at: '2026-02-28T03:00:00Z',
                },
                champion: { is_preliminary: true, promoted_at: '2026-02-27T00:00:00Z' },
                runs: [scoringRun('2026-02-28')],
            }),
            ['done', 'done', 'done', 'done', 'current'],
        ],
        [
            'a validated champion',
            input({
                pipeline: {
                    ...NEW_PIPELINE,
                    training_run_count: 2,
                    experiment_count: 9,
                    last_scored_at: '2026-02-28T03:00:00Z',
                },
                champion: { is_preliminary: false, promoted_at: '2026-01-10T00:00:00Z' },
                runs: [scoringRun('2026-02-10'), scoringRun('2026-02-11'), scoringRun('2026-02-28')],
                validatedDates: ['2026-02-10', '2026-02-10'],
            }),
            ['done', 'done', 'done', 'done', 'done'],
        ],
    ])('marks each step for %s', (_name, lifecycleInput, expectedStates) => {
        expect(pipelineLifecycle(lifecycleInput).map((step) => step.state)).toEqual(expectedStates)
    })

    it.each([
        [
            'counts distinct validated dates out of matured scored dates',
            [scoringRun('2026-02-10'), scoringRun('2026-02-11'), scoringRun('2026-02-28')],
            ['2026-02-10', '2026-02-10'],
            '1 of 2 matured dates checked',
        ],
        [
            'says when the first check comes before any date matured',
            [scoringRun('2026-02-28')],
            [],
            'First check 7 days after scoring',
        ],
    ])('%s', (_name, runs, validatedDates, expectedDetail) => {
        const steps = pipelineLifecycle(
            input({ pipeline: { ...NEW_PIPELINE, last_scored_at: '2026-02-28T03:00:00Z' }, runs, validatedDates })
        )
        expect(steps.find((step) => step.key === 'checked')?.detail.replace(/\s/g, ' ')).toEqual(expectedDetail)
    })
})
