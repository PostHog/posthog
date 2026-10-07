import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import {
    SCORE_RUN_POLL_INTERVAL_MS,
    autoresearchPipelineLogic,
    scoringCoverage,
    trainingRunProgress,
} from './autoresearchPipelineLogic'
import {
    autoresearchModelsList,
    autoresearchRetrieve,
    autoresearchRunsList,
    autoresearchRunsRetrieve,
    autoresearchScoreCreate,
} from './generated/api'
import { AutoresearchRunApi, AutoresearchTrainingRunApi, IterationTrailApi } from './generated/api.schemas'

jest.mock('./generated/api', () => ({
    autoresearchRetrieve: jest.fn(),
    autoresearchModelsList: jest.fn(),
    autoresearchTrainingRunsList: jest.fn(),
    autoresearchRunsList: jest.fn(),
    autoresearchRunsRetrieve: jest.fn(),
    autoresearchScoreCreate: jest.fn(),
    autoresearchSuggestionsList: jest.fn(),
}))

const mockRetrieve = autoresearchRetrieve as jest.Mock
const mockModelsList = autoresearchModelsList as jest.Mock
const mockRunsList = autoresearchRunsList as jest.Mock
const mockRunsRetrieve = autoresearchRunsRetrieve as jest.Mock
const mockScoreCreate = autoresearchScoreCreate as jest.Mock

function makeScoreRun(overrides: Partial<AutoresearchRunApi>): AutoresearchRunApi {
    const now = new Date().toISOString()
    return {
        id: 'score-run-1',
        pipeline: 'pipeline-1',
        model: 'champion',
        run_type: 'inference',
        status: 'running',
        rows_scored: null,
        metrics: {},
        error: '',
        started_at: now,
        completed_at: null,
        created_at: now,
        ...overrides,
    } as AutoresearchRunApi
}

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

function makeScoringRun(overrides: Partial<AutoresearchRunApi>): AutoresearchRunApi {
    return {
        id: 'scoring-run',
        pipeline: 'pipeline-1',
        run_type: 'inference',
        status: 'completed',
        rows_scored: 45000,
        metrics: { rows_eligible: 250000 },
        created_at: '2026-01-02T00:00:00Z',
        ...overrides,
    } as AutoresearchRunApi
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

    it('follows a background scoring run until it finishes, then stops polling', async () => {
        jest.clearAllMocks()
        jest.useFakeTimers()
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.AUTORESEARCH], { [FEATURE_FLAGS.AUTORESEARCH]: true })
        mockRetrieve.mockResolvedValue({ id: 'pipeline-1', name: 'Model' })
        mockModelsList.mockResolvedValue({ results: [], next: null })
        mockRunsList.mockResolvedValue({ results: [], next: null })
        mockScoreCreate.mockResolvedValue(makeScoreRun({}))
        mockRunsRetrieve
            .mockResolvedValueOnce(makeScoreRun({}))
            .mockResolvedValueOnce(makeScoreRun({ status: 'completed', rows_scored: 8000 }))
        const logic = autoresearchPipelineLogic({ id: 'pipeline-1' })
        try {
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadRunsSuccess'])

            await expectLogic(logic, () => logic.actions.scoreNow()).toDispatchActions(['scoreNowSuccess'])
            expect(logic.values.activeScoreRun?.id).toEqual('score-run-1')

            await expectLogic(logic, () => jest.advanceTimersByTime(SCORE_RUN_POLL_INTERVAL_MS)).toDispatchActions([
                'pollScoreRun',
            ])
            expect(logic.values.activeScoreRun?.id).toEqual('score-run-1')

            await expectLogic(logic, () => jest.advanceTimersByTime(SCORE_RUN_POLL_INTERVAL_MS)).toDispatchActions([
                'scoreRunFinished',
            ])
            expect(logic.values.activeScoreRun).toBeNull()
            expect(logic.cache.disposables.registry.has('scorePoll')).toBe(false)
        } finally {
            logic.unmount()
            jest.useRealTimers()
        }
    })

    it.each([
        ['resumes a run started a minute ago', 60 * 1000, 'score-run-1'],
        ['ignores a run that has been running past the stale cutoff', 6 * 60 * 60 * 1000, null],
    ])('%s when the page loads', async (_name, ageMs, expectedRunId) => {
        jest.clearAllMocks()
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.AUTORESEARCH], { [FEATURE_FLAGS.AUTORESEARCH]: true })
        mockRetrieve.mockResolvedValue({ id: 'pipeline-1', name: 'Model' })
        mockModelsList.mockResolvedValue({ results: [], next: null })
        const startedAt = new Date(Date.now() - ageMs).toISOString()
        mockRunsList.mockResolvedValue({
            results: [makeScoreRun({ started_at: startedAt, created_at: startedAt })],
            next: null,
        })
        const logic = autoresearchPipelineLogic({ id: 'pipeline-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadRunsSuccess'])
        expect(logic.values.activeScoreRun?.id ?? null).toEqual(expectedRunId)
        expect(logic.cache.disposables.registry.has('scorePoll')).toBe(expectedRunId !== null)
        logic.unmount()
    })

    describe('tabs', () => {
        async function mountWithPipeline(
            lastScoredAt: string | null,
            url: string,
            runsFail = false
        ): Promise<ReturnType<typeof autoresearchPipelineLogic.build>> {
            jest.clearAllMocks()
            initKeaTests()
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.AUTORESEARCH], {
                [FEATURE_FLAGS.AUTORESEARCH]: true,
            })
            mockRetrieve.mockResolvedValue({ id: 'pipeline-1', name: 'Model', last_scored_at: lastScoredAt })
            mockModelsList.mockResolvedValue({ results: [], next: null })
            if (runsFail) {
                mockRunsList.mockRejectedValue(new Error('runs failed'))
            } else {
                mockRunsList.mockResolvedValue({ results: [], next: null })
            }
            router.actions.push(url)
            const logic = autoresearchPipelineLogic({ id: 'pipeline-1' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadPipelineSuccess'])
            return logic
        }

        it.each([
            ['a scored model', '2026-01-02T00:00:00Z', 'predictions'],
            ['a model that never scored', null, 'agent_research'],
        ])('opens %s on its default tab', async (_name, lastScoredAt, expectedTab) => {
            const logic = await mountWithPipeline(lastScoredAt, '/autoresearch/pipeline-1')
            expect(logic.values.activeTab).toEqual(expectedTab)
            logic.unmount()
        })

        it.each([
            ['training', 'agent_research'],
            ['suggestions', 'agent_research'],
            ['online_performance', 'accuracy'],
            ['predictions', 'predictions'],
            ['overview', undefined],
            ['not_a_tab', undefined],
        ])('rewrites the old ?tab=%s link to the tab it now opens', async (oldTab, expectedUrlTab) => {
            const logic = await mountWithPipeline('2026-01-02T00:00:00Z', `/autoresearch/pipeline-1?tab=${oldTab}`)
            expect(router.values.searchParams.tab).toEqual(expectedUrlTab)
            expect(logic.values.activeTab).toEqual(expectedUrlTab ?? 'predictions')
            logic.unmount()
        })

        it('keeps the lifecycle unknown when the runs fail to load', async () => {
            const logic = await mountWithPipeline('2026-01-02T00:00:00Z', '/autoresearch/pipeline-1', true)
            await expectLogic(logic).toDispatchActions(['loadModelsSuccess', 'loadRunsFailure'])
            expect(logic.values.lifecycleSteps).toBeNull()
            logic.unmount()
        })

        it('records a tab change from the user and keeps it in the URL, but not a change from the URL', async () => {
            const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
            const logic = await mountWithPipeline(null, '/autoresearch/pipeline-1')
            capture.mockClear()

            logic.actions.setActiveTab('setup')
            expect(router.values.searchParams.tab).toEqual('setup')
            expect(capture).toHaveBeenCalledWith('autoresearch model tab changed', {
                pipeline_id: 'pipeline-1',
                tab: 'setup',
            })

            capture.mockClear()
            router.actions.push('/autoresearch/pipeline-1?tab=accuracy')
            expect(logic.values.activeTab).toEqual('accuracy')
            expect(capture).not.toHaveBeenCalledWith('autoresearch model tab changed', expect.anything())
            logic.unmount()
            capture.mockRestore()
        })
    })

    describe('scoringCoverage', () => {
        it.each([
            ['a rolling run', [makeScoringRun({})], { scored: 45000, eligible: 250000, rescoreDays: 6 }],
            ['a run that scored everyone', [makeScoringRun({ metrics: { rows_eligible: 45000 } })], null],
            ['a run from before the eligible count was recorded', [makeScoringRun({ metrics: {} })], null],
            [
                'an older rolling run superseded by a full one',
                [
                    makeScoringRun({ id: 'old', created_at: '2026-01-01T00:00:00Z' }),
                    makeScoringRun({ id: 'new', rows_scored: 900, metrics: { rows_eligible: 900 } }),
                ],
                null,
            ],
            [
                'a newer run that failed',
                [
                    makeScoringRun({}),
                    makeScoringRun({ id: 'failed', status: 'failed', created_at: '2026-01-03T00:00:00Z' }),
                ],
                { scored: 45000, eligible: 250000, rescoreDays: 6 },
            ],
        ])('reads the coverage of %s', (_name, runs, expected) => {
            expect(scoringCoverage(runs, 1)).toEqual(expected)
        })

        it('counts the rescore interval in days for a non-daily cadence', () => {
            expect(scoringCoverage([makeScoringRun({})], 7)).toEqual({
                scored: 45000,
                eligible: 250000,
                rescoreDays: 42,
            })
        })
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
