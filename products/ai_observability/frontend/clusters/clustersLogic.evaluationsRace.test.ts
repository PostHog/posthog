import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { llmEvaluationsLogic } from '../evaluations/llmEvaluationsLogic'
import { EvaluationConfig, EvaluationOutputConfig } from '../evaluations/types'
import { clustersLogic } from './clustersLogic'
import { ClusteringRun } from './types'

jest.mock('lib/api', () => {
    const actual = jest.requireActual('lib/api')

    return {
        __esModule: true,
        ...actual,
        default: {
            ...actual.default,
            queryHogQL: jest.fn(),
        },
    }
})

const evaluationWithOutputConfig = (id: string, outputConfig: EvaluationOutputConfig): EvaluationConfig =>
    ({
        id,
        name: `Evaluation ${id}`,
        description: '',
        directory_id: null,
        enabled: true,
        status: 'active',
        status_reason: null,
        status_reason_detail: null,
        evaluation_type: 'llm_judge',
        evaluation_config: { prompt: 'Prompt' },
        output_type: 'boolean',
        output_config: outputConfig,
        conditions: [],
        target: 'generation',
        target_config: {},
        model_configuration: null,
        total_runs: 0,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
    }) as EvaluationConfig

describe('clustersLogic / llmEvaluationsLogic load-order race', () => {
    let resolveEvaluationsFetch: (() => void) | undefined

    beforeEach(() => {
        const evaluationsFetchGate = new Promise<void>((resolve) => {
            resolveEvaluationsFetch = resolve
        })

        // Deliberately gated: this only resolves once the test calls resolveEvaluationsFetch(),
        // simulating llmEvaluationsLogic's own fetch losing the race against the clustering data.
        useMocks({
            get: {
                '/api/projects/:teamId/evaluations/': async () => {
                    await evaluationsFetchGate
                    return { results: [evaluationWithOutputConfig('det-1', { true_is_failure: true })] }
                },
            },
        })

        initKeaTests()
    })

    it('waits for evaluations to settle before deriving a detector verdict, instead of reading detectorEvaluationIds as []', async () => {
        const queryHogQLMock = api.queryHogQL as jest.Mock
        queryHogQLMock.mockResolvedValue({
            // eval_id, name, result, applicable, evaluation_id — matches loadEvaluationItemAttributes's SELECT
            results: [['eval-uuid-1', 'Struggle detector', 'true', null, 'det-1']],
        })

        const logic = clustersLogic()
        logic.mount()
        // afterMount fires its own unrelated loadClusteringRuns() HogQL call — clear it so the
        // assertion below only reflects the eval-attributes read this test cares about.
        queryHogQLMock.mockClear()

        const mockRun = {
            runId: 'race-run',
            windowStart: '2026-04-13T00:00:00Z',
            windowEnd: '2026-04-20T00:00:00Z',
            totalItemsAnalyzed: 1,
            clusters: [
                {
                    cluster_id: 0,
                    size: 1,
                    title: 'Detector cluster',
                    description: '',
                    traces: {
                        'eval-uuid-1': {
                            distance_to_centroid: 0,
                            rank: 0,
                            x: 0,
                            y: 0,
                            timestamp: '2026-04-20T00:00:00Z',
                            trace_id: 'eval-uuid-1',
                        },
                    },
                    centroid: [],
                    centroid_x: 0,
                    centroid_y: 0,
                },
            ],
            timestamp: '2026-04-20T00:00:00Z',
            level: 'evaluation',
        } as ClusteringRun

        // Fire the eval-level attributes loader directly — mirrors what
        // loadClusteringRunSuccess dispatches for an evaluation-level run — while
        // llmEvaluationsLogic's own evaluations fetch is still gated (evaluationsLoading is
        // true, detectorEvaluationIds is still []).
        logic.actions.loadEvaluationAttributesForRun(mockRun)

        // The gate must actually hold: the HogQL read must not fire before evaluations settle,
        // otherwise it would run with a stale, empty detectorEvaluationIds.
        expect(queryHogQLMock).not.toHaveBeenCalled()

        await expectLogic(llmEvaluationsLogic(), () => {
            resolveEvaluationsFetch?.()
        }).toDispatchActions(['loadEvaluationsSuccess'])

        await expectLogic(logic).toDispatchActions(['setEvaluationItemAttributes'])

        expect(llmEvaluationsLogic().values.detectorEvaluationIds).toEqual(['det-1'])
        expect(logic.values.evaluationItemAttributes['eval-uuid-1'].verdict).toBe('fail')

        logic.unmount()
    })

    it('does not block forever when the evaluations fetch fails — falls back to non-detector verdicts', async () => {
        const queryHogQLMock = api.queryHogQL as jest.Mock
        queryHogQLMock.mockResolvedValue({
            results: [['eval-uuid-1', 'Struggle detector', 'true', null, 'det-1']],
        })

        // Override the gated success handler from beforeEach with one that fails instead.
        useMocks({
            get: {
                '/api/projects/:teamId/evaluations/': () => [500, { detail: 'boom' }],
            },
        })

        const logic = clustersLogic()
        logic.mount()

        const mockRun = {
            runId: 'race-run-failure',
            windowStart: '2026-04-13T00:00:00Z',
            windowEnd: '2026-04-20T00:00:00Z',
            totalItemsAnalyzed: 1,
            clusters: [
                {
                    cluster_id: 0,
                    size: 1,
                    title: 'Detector cluster',
                    description: '',
                    traces: {
                        'eval-uuid-1': {
                            distance_to_centroid: 0,
                            rank: 0,
                            x: 0,
                            y: 0,
                            timestamp: '2026-04-20T00:00:00Z',
                            trace_id: 'eval-uuid-1',
                        },
                    },
                    centroid: [],
                    centroid_x: 0,
                    centroid_y: 0,
                },
            ],
            timestamp: '2026-04-20T00:00:00Z',
            level: 'evaluation',
        } as ClusteringRun

        logic.actions.loadEvaluationAttributesForRun(mockRun)

        await expectLogic(logic).toDispatchActions(['setEvaluationItemAttributes'])

        // A failed evaluations fetch must not hang the scene: detectorEvaluationIds stays [],
        // so the verdict falls back to today's non-detector reading rather than never resolving.
        expect(llmEvaluationsLogic().values.detectorEvaluationIds).toEqual([])
        expect(logic.values.evaluationItemAttributes['eval-uuid-1'].verdict).toBe('pass')

        logic.unmount()
    })
})
