import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { autoresearchPipelineLogic, trainingRunProgress } from './autoresearchPipelineLogic'
import { autoresearchModelsList, autoresearchRetrieve } from './generated/api'
import { AutoresearchTrainingRunApi, IterationTrailApi } from './generated/api.schemas'

jest.mock('./generated/api', () => ({
    autoresearchRetrieve: jest.fn(),
    autoresearchModelsList: jest.fn(),
    autoresearchTrainingRunsList: jest.fn(),
    autoresearchRunsList: jest.fn(),
    autoresearchSuggestionsList: jest.fn(),
}))

const mockRetrieve = autoresearchRetrieve as jest.Mock
const mockModelsList = autoresearchModelsList as jest.Mock

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

describe('autoresearchPipelineLogic', () => {
    it('follows every page of models so a champion past the first page still counts', async () => {
        jest.clearAllMocks()
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.AUTORESEARCH], { [FEATURE_FLAGS.AUTORESEARCH]: true })
        mockRetrieve.mockResolvedValue({ id: 'pipeline-1', name: 'Model' })
        mockModelsList
            .mockResolvedValueOnce({ results: [{ id: 'challenger', role: 'challenger' }], next: 'page-2' })
            .mockResolvedValueOnce({ results: [{ id: 'champion', role: 'champion' }], next: null })
        const logic = autoresearchPipelineLogic({ id: 'pipeline-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.models.map((m) => m.id)).toEqual(['challenger', 'champion'])
        expect(mockModelsList).toHaveBeenLastCalledWith(expect.any(String), 'pipeline-1', { offset: 1 })
    })

    it('waits for the flag before it loads the model, then loads once', async () => {
        jest.clearAllMocks()
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {})
        mockRetrieve.mockResolvedValue({ id: 'pipeline-1', name: 'Model' })
        const logic = autoresearchPipelineLogic({ id: 'pipeline-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockRetrieve).not.toHaveBeenCalled()

        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.AUTORESEARCH], { [FEATURE_FLAGS.AUTORESEARCH]: true })
        await expectLogic(logic).toFinishAllListeners()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.AUTORESEARCH], { [FEATURE_FLAGS.AUTORESEARCH]: true })
        await expectLogic(logic).toFinishAllListeners()
        expect(mockRetrieve).toHaveBeenCalledTimes(1)
    })

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

        it('uses the persisted fields once the run completes', () => {
            const run = makeRun({
                status: 'completed',
                iteration_count: 5,
                best_holdout_score: 0.81,
                // Persisted fields win at terminal state even if the serialized trail differs.
                iterations: [makeIteration({ iteration_number: 0, holdout_score: 0.5 })],
            })
            expect(trainingRunProgress(run)).toEqual({ iterationCount: 5, bestHoldoutScore: 0.81 })
        })

        it('reads the recorded iterations of a failed run, whose counters were never written', () => {
            const run = makeRun({
                status: 'failed',
                iteration_count: 0,
                best_holdout_score: null,
                iterations: [
                    makeIteration({ iteration_number: 0, holdout_score: 0.64 }),
                    makeIteration({ iteration_number: 1, holdout_score: 0.7 }),
                ],
            })
            expect(trainingRunProgress(run)).toEqual({ iterationCount: 2, bestHoldoutScore: 0.7 })
        })
    })
})
