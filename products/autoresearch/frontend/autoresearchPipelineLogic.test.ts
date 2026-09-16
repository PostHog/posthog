import { trainingRunProgress } from './autoresearchPipelineLogic'
import { AutoresearchTrainingRunApi, IterationTrailApi } from './generated/api.schemas'

function makeRun(overrides: Partial<AutoresearchTrainingRunApi>): AutoresearchTrainingRunApi {
    return {
        id: 'run-1',
        pipeline: 'pipeline-1',
        task_url: null,
        status: 'running',
        iteration_count: 0,
        best_holdout_score: null,
        summary: null,
        iterations: [],
        error: '',
        started_at: null,
        completed_at: null,
        created_at: '2026-01-01T00:00:00Z',
        ...overrides,
    } as AutoresearchTrainingRunApi
}

function makeIteration(overrides: Partial<IterationTrailApi>): IterationTrailApi {
    return {
        iteration_number: 0,
        status: 'kept',
        holdout_score: null,
        ...overrides,
    } as IterationTrailApi
}

describe('trainingRunProgress', () => {
    it('derives progress from live iteration rows while the run is in flight', () => {
        // Persisted fields are only written at completion, so they read 0 / null here.
        const run = makeRun({
            status: 'running',
            iteration_count: 0,
            best_holdout_score: null,
            iterations: [
                makeIteration({ iteration_number: 0, holdout_score: 0.61 }),
                makeIteration({ iteration_number: 1, holdout_score: 0.72 }),
                makeIteration({ iteration_number: 2, status: 'crashed', holdout_score: null }),
            ],
        })
        expect(trainingRunProgress(run)).toEqual({ iterationCount: 3, bestHoldoutScore: 0.72 })
    })

    it('reports no score for an in-flight run whose iterations have no holdout scores yet', () => {
        const run = makeRun({
            status: 'running',
            iterations: [makeIteration({ iteration_number: 0, status: 'discarded', holdout_score: null })],
        })
        expect(trainingRunProgress(run)).toEqual({ iterationCount: 1, bestHoldoutScore: null })
    })

    it.each(['completed', 'failed'] as const)('uses the persisted fields once the run is %s', (status) => {
        const run = makeRun({
            status,
            iteration_count: 5,
            best_holdout_score: 0.81,
            // Persisted fields win at terminal state even if the serialized trail differs.
            iterations: [makeIteration({ iteration_number: 0, holdout_score: 0.5 })],
        })
        expect(trainingRunProgress(run)).toEqual({ iterationCount: 5, bestHoldoutScore: 0.81 })
    })
})
