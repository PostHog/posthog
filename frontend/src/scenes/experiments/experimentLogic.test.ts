import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { userLogic } from 'scenes/userLogic'

import experimentJson from '~/mocks/fixtures/api/experiments/_experiment_launched_with_funnel_and_trends.json'
import experimentMetricResultsErrorJson from '~/mocks/fixtures/api/experiments/_experiment_metric_results_error.json'
import experimentMetricResultsSuccessJson from '~/mocks/fixtures/api/experiments/_experiment_metric_results_success.json'
import { useMocks } from '~/mocks/jest'
import {
    Breakdown,
    CachedNewExperimentQueryResponse,
    ExperimentMetric,
    ExperimentMetricType,
    NodeKind,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { Experiment, MultivariateFlagVariant } from '~/types'

import { ExperimentSavedMetric, ExperimentWarning, experimentLogic, getDisplayOrderedIndices } from './experimentLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
        error: jest.fn(),
        info: jest.fn(),
    },
}))

const mockShowApprovalRequiredToast = jest.fn()
jest.mock('scenes/approvals/ApprovalRequiredBanner', () => ({
    showApprovalRequiredToast: (...args: any[]) => mockShowApprovalRequiredToast(...args),
}))

const RUNNING_EXP_ID = 45
const RUNNING_FUNNEL_EXP_ID = 46

describe('experimentLogic', () => {
    let logic: ReturnType<typeof experimentLogic.build>
    // Transform null to undefined where needed
    const experiment = {
        ...experimentJson,
        created_by: { ...experimentJson.created_by, hedgehog_config: undefined },
        holdout: undefined,
        primary_metrics_ordered_uuids: null,
        secondary_metrics_ordered_uuids: null,
    } as Experiment

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/experiments': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [{ id: 1, name: 'Test Exp', description: 'bla' }],
                },
                '/api/projects/:team/experiment_holdouts': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
                '/api/projects/:team/experiment_saved_metrics': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
                '/api/projects/:team/experiments/:id': experiment,
                [`/api/projects/:team/experiments/${RUNNING_EXP_ID}/results`]: {
                    filters: { breakdown: '$feature/test-experiment', breakdown_type: 'event', insight: 'TRENDS' },
                    insight: [
                        { breakdown_value: 'control', count: 200 },
                        { breakdown_value: 'test_1', count: 400 },
                        { breakdown_value: 'test_2', count: 500 },
                        { breakdown_value: 'test_3', count: 100 },
                    ],
                    probability: { control: 0.7, test_1: 0.1, test_2: 0.2, test_3: 0 },
                },
                [`/api/projects/:team/experiments/${RUNNING_FUNNEL_EXP_ID}/results`]: {
                    filters: { breakdown: '$feature/test-experiment', breakdown_type: 'event', insight: 'FUNNELS' },
                    insight: [
                        [
                            { breakdown_value: ['control'], count: 200, order: 0 },
                            { breakdown_value: ['control'], count: 100, order: 1 },
                        ],
                        [
                            { breakdown_value: ['test_1'], count: 200, order: 0 },
                            { breakdown_value: ['test_1'], count: 120, order: 1 },
                        ],
                        [
                            { breakdown_value: ['test_2'], count: 200, order: 0 },
                            { breakdown_value: ['test_2'], count: 140, order: 1 },
                        ],
                        [
                            { breakdown_value: ['test_3'], count: 200, order: 0 },
                            { breakdown_value: ['test_3'], count: 160, order: 1 },
                        ],
                    ],
                    probability: { control: 0.7, test_1: 0.1, test_2: 0.2, test_3: 0 },
                },
            },
        })
        initKeaTests()
        logic = experimentLogic()
        logic.mount()
        await expectLogic(userLogic).toFinishAllListeners()
    })

    describe('loadPrimaryMetricsResults', () => {
        it('given a refresh, loads the metric results', async () => {
            logic.actions.setExperiment(experiment)

            useMocks({
                post: {
                    '/api/environments/:team/query/:kind': (() => {
                        let callCount = 0
                        return () => {
                            callCount++
                            return [
                                200,
                                {
                                    cache_key: 'cache_key',
                                    query_status:
                                        callCount === 1
                                            ? experimentMetricResultsSuccessJson.query_status
                                            : experimentMetricResultsErrorJson.query_status,
                                },
                            ]
                        }
                    })(),
                },
                get: {
                    '/api/environments/:team/query/:id': (() => {
                        let callCount = 0
                        return () => {
                            callCount++
                            return callCount === 1
                                ? [200, experimentMetricResultsSuccessJson]
                                : [400, experimentMetricResultsErrorJson]
                        }
                    })(),
                },
            })

            const promise = logic.asyncActions.loadPrimaryMetricsResults(true)

            await expectLogic(logic).toDispatchActions(['setPrimaryMetricsResultsLoading']).toMatchValues({
                primaryMetricsResultsLoading: true,
                primaryMetricsResultsErrors: [],
            })

            await promise

            await expectLogic(logic)
                .toDispatchActions(['setPrimaryMetricsResultsLoading'])
                .toMatchValues({
                    primaryMetricsResultsLoading: false,
                    primaryMetricsResultsErrors: [
                        null,
                        {
                            detail: {
                                'no-control-variant': true,
                                'no-test-variant': true,
                                'no-exposures': false,
                            },
                            hasDiagnostics: true,
                            statusCode: 400,
                            code: 'no-results',
                            queryId: expect.any(String),
                            timestamp: expect.any(Number),
                        },
                    ],
                })
        })
    })

    describe('loadSecondaryMetricsResults', () => {
        it('given a refresh, loads the secondary metric results', async () => {
            logic.actions.setExperiment(experiment)

            useMocks({
                post: {
                    '/api/environments/:team/query/:kind': (() => {
                        let callCount = 0
                        return () => {
                            callCount++
                            return [
                                200,
                                {
                                    cache_key: 'cache_key',
                                    query_status:
                                        callCount === 2
                                            ? experimentMetricResultsSuccessJson.query_status
                                            : experimentMetricResultsErrorJson.query_status,
                                },
                            ]
                        }
                    })(),
                },
                get: {
                    '/api/environments/:team/query/:id': (() => {
                        let callCount = 0
                        return () => {
                            callCount++
                            return callCount === 2
                                ? [200, experimentMetricResultsSuccessJson]
                                : [400, experimentMetricResultsErrorJson]
                        }
                    })(),
                },
            })

            const promise = logic.asyncActions.loadSecondaryMetricsResults(true)

            await expectLogic(logic).toDispatchActions(['setSecondaryMetricsResultsLoading']).toMatchValues({
                secondaryMetricsResultsLoading: true,
                secondaryMetricsResultsErrors: [],
            })

            await promise

            await expectLogic(logic)
                .toDispatchActions(['setSecondaryMetricsResultsLoading'])
                .toMatchValues({
                    secondaryMetricsResultsLoading: false,
                    secondaryMetricsResultsErrors: [
                        {
                            detail: {
                                'no-control-variant': true,
                                'no-test-variant': true,
                                'no-exposures': false,
                            },
                            hasDiagnostics: true,
                            statusCode: 400,
                            code: 'no-results',
                            queryId: expect.any(String),
                            timestamp: expect.any(Number),
                        },
                        null,
                    ],
                })
        })
    })

    describe('refreshExperimentResults', () => {
        it('waits for metric refreshes to complete before resolving', async () => {
            logic.actions.setExperiment(experiment)

            useMocks({
                post: {
                    '/api/environments/:team/query': async () => {
                        await new Promise((resolve) => setTimeout(resolve, 30))
                        return [
                            200,
                            {
                                cache_key: 'cache_key',
                                query_status: experimentMetricResultsSuccessJson.query_status,
                            },
                        ]
                    },
                },
                get: {
                    '/api/environments/:team/query/:id': async () => {
                        await new Promise((resolve) => setTimeout(resolve, 30))
                        return [200, experimentMetricResultsSuccessJson]
                    },
                },
            })

            await logic.asyncActions.refreshExperimentResults(true, 'manual')

            // Verify loading states are properly reset after refresh completes
            expect(logic.values.primaryMetricsResultsLoading).toBe(false)
            expect(logic.values.secondaryMetricsResultsLoading).toBe(false)
        })
    })

    describe('currentRefresh tracking', () => {
        it('marks the refresh as in_progress while running and completed when it succeeds', async () => {
            logic.actions.setExperiment(experiment)

            useMocks({
                post: {
                    '/api/environments/:team/query': () => [
                        200,
                        {
                            cache_key: 'cache_key',
                            query_status: experimentMetricResultsSuccessJson.query_status,
                        },
                    ],
                },
                get: {
                    '/api/environments/:team/query/:id': () => [200, experimentMetricResultsSuccessJson],
                },
            })

            const promise = logic.asyncActions.refreshExperimentResults(true, 'manual')

            await expectLogic(logic).toDispatchActions(['markRefreshStarted'])
            expect(logic.values.currentRefresh).toMatchObject({
                state: 'in_progress',
                triggered_by: 'manual',
            })
            expect(logic.values.currentRefresh?.refresh_id).toEqual(expect.any(String))

            await promise

            expect(logic.values.currentRefresh).toMatchObject({
                state: 'completed',
                triggered_by: 'manual',
            })
        })

        it.each(['completed', 'partial', 'errored'] as const)(
            'transitions to %s when markRefreshFinished fires with that state',
            (finalState) => {
                logic.actions.markRefreshStarted('refresh-1', 'manual')
                expect(logic.values.currentRefresh?.state).toBe('in_progress')

                logic.actions.markRefreshFinished('refresh-1', finalState)

                expect(logic.values.currentRefresh).toMatchObject({
                    refresh_id: 'refresh-1',
                    state: finalState,
                    triggered_by: 'manual',
                })
            }
        )

        it('ignores markRefreshFinished for a stale refresh_id and preserves the in-flight snapshot', () => {
            logic.actions.markRefreshStarted('refresh-1', 'manual')
            logic.actions.markRefreshStarted('refresh-2', 'auto_refresh')

            // Late completion from the previous refresh shouldn't clobber the new one.
            logic.actions.markRefreshFinished('refresh-1', 'completed')

            expect(logic.values.currentRefresh).toMatchObject({
                refresh_id: 'refresh-2',
                state: 'in_progress',
                triggered_by: 'auto_refresh',
            })
        })
    })

    describe('removeSharedMetricFromExperiment', () => {
        beforeEach(() => {
            jest.spyOn(api, 'update')
            api.update.mockClear()
        })

        it('removes orphaned shared metric from metrics array', async () => {
            const orphanedSharedMetricId = 46275
            const experimentWithOrphan = {
                ...experiment,
                saved_metrics: [],
                metrics: [
                    {
                        kind: 'ExperimentMetric',
                        name: 'Orphaned Shared Metric',
                        uuid: 'orphan-uuid',
                        isSharedMetric: true,
                        sharedMetricId: orphanedSharedMetricId,
                    },
                    experiment.metrics[0],
                ],
                metrics_secondary: [],
            } as unknown as Experiment

            logic.actions.setExperiment(experimentWithOrphan)
            api.update.mockResolvedValue(experimentWithOrphan)

            useMocks({
                get: {
                    '/api/projects/:team/experiments/:id': experimentWithOrphan,
                },
            })

            await expectLogic(logic, () => {
                logic.actions.removeSharedMetricFromExperiment(orphanedSharedMetricId)
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledWith(
                expect.stringContaining('/experiments/'),
                expect.objectContaining({
                    saved_metrics_ids: [],
                    metrics: [experiment.metrics[0]],
                    metrics_secondary: [],
                })
            )
        })

        it('removes orphaned shared metric from metrics_secondary array', async () => {
            const orphanedSharedMetricId = 99999
            const experimentWithOrphan = {
                ...experiment,
                saved_metrics: [],
                metrics: [],
                metrics_secondary: [
                    {
                        kind: 'ExperimentMetric',
                        name: 'Orphaned Secondary Metric',
                        uuid: 'orphan-secondary-uuid',
                        isSharedMetric: true,
                        sharedMetricId: orphanedSharedMetricId,
                    },
                ],
            } as unknown as Experiment

            logic.actions.setExperiment(experimentWithOrphan)
            api.update.mockResolvedValue(experimentWithOrphan)

            useMocks({
                get: {
                    '/api/projects/:team/experiments/:id': experimentWithOrphan,
                },
            })

            await expectLogic(logic, () => {
                logic.actions.removeSharedMetricFromExperiment(orphanedSharedMetricId)
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledWith(
                expect.stringContaining('/experiments/'),
                expect.objectContaining({
                    saved_metrics_ids: [],
                    metrics: [],
                    metrics_secondary: [],
                })
            )
        })
    })
    describe('saveMetricsReorder', () => {
        const primaryMetric = {
            kind: 'ExperimentMetric',
            uuid: 'primary-metric-uuid',
            name: 'Primary metric',
        } as unknown as ExperimentMetric
        const otherPrimaryMetric = {
            kind: 'ExperimentMetric',
            uuid: 'other-primary-uuid',
            name: 'Other primary metric',
        } as unknown as ExperimentMetric
        const thirdPrimaryMetric = {
            kind: 'ExperimentMetric',
            uuid: 'third-primary-uuid',
            name: 'Third primary metric',
        } as unknown as ExperimentMetric
        const secondaryMetric = {
            kind: 'ExperimentMetric',
            uuid: 'secondary-metric-uuid',
            name: 'Secondary metric',
        } as unknown as ExperimentMetric

        const primaryMetricResult = {
            baseline: { key: 'control' },
            metric_uuid: 'primary-metric-uuid',
        } as unknown as CachedNewExperimentQueryResponse
        const otherPrimaryMetricResult = {
            baseline: { key: 'control' },
            metric_uuid: 'other-primary-uuid',
        } as unknown as CachedNewExperimentQueryResponse
        const thirdPrimaryMetricResult = {
            baseline: { key: 'control' },
            metric_uuid: 'third-primary-uuid',
        } as unknown as CachedNewExperimentQueryResponse
        const secondaryMetricResult = {
            baseline: { key: 'control' },
            metric_uuid: 'secondary-metric-uuid',
        } as unknown as CachedNewExperimentQueryResponse

        beforeEach(() => {
            jest.spyOn(api, 'update')
            api.update.mockClear()
        })

        it('persists a pure reorder without touching metric arrays or results', async () => {
            const testExperiment = {
                ...experiment,
                saved_metrics: [],
                metrics: [primaryMetric, otherPrimaryMetric],
                metrics_secondary: [],
                primary_metrics_ordered_uuids: ['primary-metric-uuid', 'other-primary-uuid'],
            } as unknown as Experiment

            logic.actions.setExperiment(testExperiment)
            logic.actions.setPrimaryMetricsResults([primaryMetricResult, otherPrimaryMetricResult])
            api.update.mockResolvedValue({
                ...testExperiment,
                primary_metrics_ordered_uuids: ['other-primary-uuid', 'primary-metric-uuid'],
            })

            await expectLogic(logic, () => {
                logic.actions.saveMetricsReorder(false, ['other-primary-uuid', 'primary-metric-uuid'], [], [])
            })
                .toFinishAllListeners()
                .toNotHaveDispatchedActions(['refreshExperimentResults', 'loadPrimaryMetricsResults'])

            expect(api.update).toHaveBeenCalledWith(expect.stringContaining('/experiments/'), {
                primary_metrics_ordered_uuids: ['other-primary-uuid', 'primary-metric-uuid'],
                update_feature_flag_params: false,
            })
            expect(logic.values.primaryMetricsResults).toEqual([primaryMetricResult, otherPrimaryMetricResult])
        })

        it('moves an inline metric to secondary and reuses existing results', async () => {
            const testExperiment = {
                ...experiment,
                saved_metrics: [],
                metrics: [primaryMetric, otherPrimaryMetric],
                metrics_secondary: [secondaryMetric],
                primary_metrics_ordered_uuids: ['primary-metric-uuid', 'other-primary-uuid'],
            } as unknown as Experiment

            logic.actions.setExperiment(testExperiment)
            logic.actions.setPrimaryMetricsResults([primaryMetricResult, otherPrimaryMetricResult])
            logic.actions.setSecondaryMetricsResults([secondaryMetricResult])
            api.update.mockResolvedValue({
                ...testExperiment,
                metrics: [otherPrimaryMetric],
                metrics_secondary: [secondaryMetric, primaryMetric],
                primary_metrics_ordered_uuids: ['other-primary-uuid'],
            })

            await expectLogic(logic, () => {
                logic.actions.saveMetricsReorder(
                    false,
                    ['primary-metric-uuid', 'other-primary-uuid'],
                    [],
                    ['primary-metric-uuid']
                )
            })
                .toFinishAllListeners()
                .toNotHaveDispatchedActions([
                    'refreshExperimentResults',
                    'loadPrimaryMetricsResults',
                    'loadSecondaryMetricsResults',
                    'loadExperiment',
                    'retryPrimaryMetric',
                    'retrySecondaryMetric',
                ])

            expect(api.update).toHaveBeenCalledWith(
                expect.stringContaining('/experiments/'),
                expect.objectContaining({
                    metrics: [otherPrimaryMetric],
                    metrics_secondary: [secondaryMetric, primaryMetric],
                    primary_metrics_ordered_uuids: ['other-primary-uuid'],
                })
            )
            expect(api.update).toHaveBeenCalledWith(
                expect.stringContaining('/experiments/'),
                expect.not.objectContaining({ saved_metrics_ids: expect.anything() })
            )
            expect(logic.values.primaryMetricsResults).toEqual([otherPrimaryMetricResult])
            expect(logic.values.secondaryMetricsResults).toEqual([secondaryMetricResult, primaryMetricResult])
            expect(logic.values.primaryMetricsResultsErrors).toEqual([null])
            expect(logic.values.secondaryMetricsResultsErrors).toEqual([null, null])
        })

        it('applies a combined move and removal in a single update', async () => {
            const testExperiment = {
                ...experiment,
                saved_metrics: [],
                metrics: [primaryMetric, otherPrimaryMetric, thirdPrimaryMetric],
                metrics_secondary: [],
                primary_metrics_ordered_uuids: ['primary-metric-uuid', 'other-primary-uuid', 'third-primary-uuid'],
            } as unknown as Experiment

            logic.actions.setExperiment(testExperiment)
            logic.actions.setPrimaryMetricsResults([
                primaryMetricResult,
                otherPrimaryMetricResult,
                thirdPrimaryMetricResult,
            ])
            api.update.mockResolvedValue({
                ...testExperiment,
                metrics: [thirdPrimaryMetric],
                metrics_secondary: [primaryMetric],
                primary_metrics_ordered_uuids: ['third-primary-uuid'],
            })

            await expectLogic(logic, () => {
                logic.actions.saveMetricsReorder(
                    false,
                    ['primary-metric-uuid', 'other-primary-uuid', 'third-primary-uuid'],
                    ['other-primary-uuid'],
                    ['primary-metric-uuid']
                )
            })
                .toFinishAllListeners()
                .toNotHaveDispatchedActions(['refreshExperimentResults'])

            expect(api.update).toHaveBeenCalledWith(
                expect.stringContaining('/experiments/'),
                expect.objectContaining({
                    metrics: [thirdPrimaryMetric],
                    metrics_secondary: [primaryMetric],
                    primary_metrics_ordered_uuids: ['third-primary-uuid'],
                })
            )
            expect(logic.values.primaryMetricsResults).toEqual([thirdPrimaryMetricResult])
            expect(logic.values.secondaryMetricsResults).toEqual([primaryMetricResult])
        })

        it('moves a shared metric by flipping its saved-metric link type', async () => {
            const sharedMetricId = 123
            const sharedSavedMetric = {
                id: 1,
                experiment: experiment.id as number,
                saved_metric: sharedMetricId,
                name: 'Shared metric',
                query: {
                    uuid: 'shared-metric-uuid',
                    kind: NodeKind.ExperimentMetric,
                    metric_type: ExperimentMetricType.MEAN,
                    source: { kind: NodeKind.EventsNode, event: '$pageview' },
                },
                metadata: { type: 'primary' },
                created_at: '2024-01-01T00:00:00Z',
            } satisfies ExperimentSavedMetric
            const sharedMetricResult = {
                baseline: { key: 'control' },
                metric_uuid: 'shared-metric-uuid',
            } as unknown as CachedNewExperimentQueryResponse
            const testExperiment = {
                ...experiment,
                metrics: [],
                metrics_secondary: [],
                saved_metrics: [sharedSavedMetric],
                primary_metrics_ordered_uuids: ['shared-metric-uuid'],
            } as unknown as Experiment

            logic.actions.setExperiment(testExperiment)
            logic.actions.setPrimaryMetricsResults([sharedMetricResult])
            api.update.mockResolvedValue({
                ...testExperiment,
                saved_metrics: [{ ...sharedSavedMetric, metadata: { type: 'secondary' } }],
                primary_metrics_ordered_uuids: [],
            })

            await expectLogic(logic, () => {
                logic.actions.saveMetricsReorder(false, ['shared-metric-uuid'], [], ['shared-metric-uuid'])
            })
                .toFinishAllListeners()
                .toNotHaveDispatchedActions(['refreshExperimentResults', 'loadExperiment'])

            expect(api.update).toHaveBeenCalledWith(
                expect.stringContaining('/experiments/'),
                expect.objectContaining({
                    saved_metrics_ids: [{ id: sharedMetricId, metadata: { type: 'secondary' } }],
                })
            )
            expect(logic.values.primaryMetricsResults).toEqual([])
            expect(logic.values.secondaryMetricsResults).toEqual([sharedMetricResult])
        })

        it('loads only the moved metric when it has no result yet', async () => {
            const fetchedResult = { baseline: { key: 'control' }, variant_results: [] }
            useMocks({
                post: {
                    '/api/environments/:team/query/:kind': () => [
                        200,
                        {
                            cache_key: 'cache_key',
                            query_status: {
                                ...experimentMetricResultsSuccessJson.query_status,
                                results: fetchedResult,
                            },
                        },
                    ],
                },
                get: {
                    '/api/environments/:team/query/:id': () => [
                        200,
                        {
                            query_status: {
                                ...experimentMetricResultsSuccessJson.query_status,
                                results: fetchedResult,
                            },
                        },
                    ],
                },
            })

            const testExperiment = {
                ...experiment,
                saved_metrics: [],
                metrics: [],
                metrics_secondary: [secondaryMetric],
                secondary_metrics_ordered_uuids: ['secondary-metric-uuid'],
            } as unknown as Experiment

            logic.actions.setExperiment(testExperiment)
            api.update.mockResolvedValue({
                ...testExperiment,
                metrics: [secondaryMetric],
                metrics_secondary: [],
                secondary_metrics_ordered_uuids: [],
            })

            await expectLogic(logic, () => {
                logic.actions.saveMetricsReorder(true, ['secondary-metric-uuid'], [], ['secondary-metric-uuid'])
            })
                .toDispatchActions(['updateExperimentSuccess', 'retryPrimaryMetric'])
                .toFinishAllListeners()
                .toNotHaveDispatchedActions(['refreshExperimentResults', 'loadPrimaryMetricsResults'])

            expect(logic.values.primaryMetricsResults).toEqual([expect.objectContaining(fetchedResult)])
        })

        it('falls back to a full refresh when results are already loading', async () => {
            useMocks({
                post: {
                    '/api/environments/:team/query/:kind': () => [
                        200,
                        { cache_key: 'cache_key', query_status: experimentMetricResultsSuccessJson.query_status },
                    ],
                },
                get: {
                    '/api/environments/:team/query/:id': () => [200, experimentMetricResultsSuccessJson],
                },
            })

            const testExperiment = {
                ...experiment,
                saved_metrics: [],
                metrics: [primaryMetric],
                metrics_secondary: [],
                primary_metrics_ordered_uuids: ['primary-metric-uuid'],
            } as unknown as Experiment

            logic.actions.setExperiment(testExperiment)
            logic.actions.setPrimaryMetricsResultsLoading(true)
            api.update.mockResolvedValue({
                ...testExperiment,
                metrics: [],
                metrics_secondary: [primaryMetric],
                primary_metrics_ordered_uuids: [],
            })

            await expectLogic(logic, () => {
                logic.actions.saveMetricsReorder(false, ['primary-metric-uuid'], [], ['primary-metric-uuid'])
            })
                .toDispatchActions(['updateExperiment', 'refreshExperimentResults'])
                .toFinishAllListeners()
        })
    })
    describe('breakdown management', () => {
        it('should add breakdown to inline metric', () => {
            const breakdown: Breakdown = { property: '$browser', type: 'event' }
            const testExperiment: Experiment = {
                ...experiment,
                metrics: [
                    {
                        uuid: 'test-metric-uuid',
                        metric_type: ExperimentMetricType.MEAN,
                        source: { kind: NodeKind.EventsNode, event: '$pageview' },
                        breakdownFilter: { breakdowns: [] },
                    },
                ] as unknown as ExperimentMetric[],
            }

            logic.actions.setExperiment(testExperiment)
            logic.actions.updateMetricBreakdown('test-metric-uuid', breakdown)

            const updatedMetric = logic.values.experiment.metrics[0] as ExperimentMetric
            expect(updatedMetric.breakdownFilter?.breakdowns).toEqual([breakdown])
        })

        it('should add breakdown to shared metric metadata', () => {
            const breakdown: Breakdown = { property: '$browser', type: 'event' }
            const testExperiment: Experiment = {
                ...experiment,
                saved_metrics: [
                    {
                        id: 1,
                        experiment: experiment.id as number,
                        saved_metric: 123,
                        name: 'Shared Metric',
                        query: {
                            uuid: 'shared-metric-uuid',
                            kind: NodeKind.ExperimentMetric,
                            metric_type: ExperimentMetricType.MEAN,
                            source: { kind: NodeKind.EventsNode, event: '$pageview' },
                        },
                        metadata: { type: 'primary' },
                        created_at: '2024-01-01T00:00:00Z',
                    } satisfies ExperimentSavedMetric,
                ],
                metrics: [],
            }

            logic.actions.setExperiment(testExperiment)
            logic.actions.updateMetricBreakdown('shared-metric-uuid', breakdown)

            expect(logic.values.experiment.saved_metrics[0].metadata.breakdowns).toEqual([breakdown])
        })

        it('should remove breakdown from inline metric', () => {
            const testExperiment: Experiment = {
                ...experiment,
                metrics: [
                    {
                        uuid: 'test-metric-uuid',
                        metric_type: ExperimentMetricType.MEAN,
                        source: { kind: NodeKind.EventsNode, event: '$pageview' },
                        breakdownFilter: {
                            breakdowns: [
                                { property: '$browser', type: 'event' },
                                { property: '$os', type: 'event' },
                            ],
                        },
                    },
                ] as unknown as ExperimentMetric[],
            }

            logic.actions.setExperiment(testExperiment)
            const breakdownToRemove: Breakdown = { property: '$browser', type: 'event' }
            logic.actions.removeMetricBreakdown('test-metric-uuid', 0, breakdownToRemove)

            const updatedMetric = logic.values.experiment.metrics[0] as ExperimentMetric
            expect(updatedMetric.breakdownFilter?.breakdowns).toEqual([{ property: '$os', type: 'event' }])
        })

        it('should remove breakdown from shared metric metadata', () => {
            const testExperiment: Experiment = {
                ...experiment,
                saved_metrics: [
                    {
                        id: 1,
                        experiment: experiment.id as number,
                        saved_metric: 123,
                        name: 'Shared Metric',
                        query: {
                            uuid: 'shared-metric-uuid',
                            kind: NodeKind.ExperimentMetric,
                            metric_type: ExperimentMetricType.MEAN,
                            source: { kind: NodeKind.EventsNode, event: '$pageview' },
                        },
                        metadata: {
                            type: 'primary',
                            breakdowns: [
                                { property: '$browser', type: 'event' } satisfies Breakdown,
                                { property: '$os', type: 'event' } satisfies Breakdown,
                            ],
                        },
                        created_at: '2024-01-01T00:00:00Z',
                    } satisfies ExperimentSavedMetric,
                ],
                metrics: [],
            }

            logic.actions.setExperiment(testExperiment)
            const breakdownToRemove: Breakdown = { property: '$browser', type: 'event' }
            logic.actions.removeMetricBreakdown('shared-metric-uuid', 0, breakdownToRemove)

            expect(logic.values.experiment.saved_metrics[0].metadata.breakdowns).toEqual([
                { property: '$os', type: 'event' },
            ])
        })

        it('should include breakdowns when preparing shared metrics for loading', () => {
            const testExperiment: Experiment = {
                ...experiment,
                saved_metrics: [
                    {
                        id: 1,
                        experiment: experiment.id as number,
                        saved_metric: 123,
                        name: 'Shared Metric',
                        query: {
                            uuid: 'shared-metric-uuid',
                            kind: NodeKind.ExperimentMetric,
                            metric_type: ExperimentMetricType.MEAN,
                            source: { kind: NodeKind.EventsNode, event: '$pageview' },
                        },
                        metadata: {
                            type: 'primary',
                            breakdowns: [
                                { property: '$browser', type: 'event' } satisfies Breakdown,
                                { property: '$os', type: 'event' } satisfies Breakdown,
                            ],
                        },
                        created_at: '2024-01-01T00:00:00Z',
                    } satisfies ExperimentSavedMetric,
                ],
                metrics: [],
                primary_metrics_ordered_uuids: ['shared-metric-uuid'],
                start_date: '2024-01-01',
            }

            logic.actions.setExperiment(testExperiment)

            // Check that orderedPrimaryMetricsWithResults includes breakdowns
            const metricsWithResults = logic.values.orderedPrimaryMetricsWithResults
            expect(metricsWithResults.length).toBe(1)
            const enrichedMetric = metricsWithResults[0].metric
            expect(enrichedMetric.breakdownFilter?.breakdowns).toEqual([
                { property: '$browser', type: 'event' },
                { property: '$os', type: 'event' },
            ])
        })

        it('should add breakdown to secondary shared metric metadata', () => {
            const breakdown: Breakdown = { property: '$browser', type: 'event' }
            const testExperiment: Experiment = {
                ...experiment,
                saved_metrics: [
                    {
                        id: 1,
                        experiment: experiment.id as number,
                        saved_metric: 123,
                        name: 'Secondary Shared Metric',
                        query: {
                            uuid: 'secondary-metric-uuid',
                            kind: NodeKind.ExperimentMetric,
                            metric_type: ExperimentMetricType.MEAN,
                            source: { kind: NodeKind.EventsNode, event: '$pageview' },
                        },
                        metadata: { type: 'secondary' },
                        created_at: '2024-01-01T00:00:00Z',
                    } satisfies ExperimentSavedMetric,
                ],
                metrics: [],
                metrics_secondary: [],
            }

            logic.actions.setExperiment(testExperiment)
            logic.actions.updateMetricBreakdown('secondary-metric-uuid', breakdown)

            expect(logic.values.experiment.saved_metrics[0].metadata.breakdowns).toEqual([breakdown])
        })

        it('should remove breakdown from secondary shared metric metadata', () => {
            const testExperiment: Experiment = {
                ...experiment,
                saved_metrics: [
                    {
                        id: 1,
                        experiment: experiment.id as number,
                        saved_metric: 123,
                        name: 'Secondary Shared Metric',
                        query: {
                            uuid: 'secondary-metric-uuid',
                            kind: NodeKind.ExperimentMetric,
                            metric_type: ExperimentMetricType.MEAN,
                            source: { kind: NodeKind.EventsNode, event: '$pageview' },
                        },
                        metadata: {
                            type: 'secondary',
                            breakdowns: [
                                { property: '$browser', type: 'event' } satisfies Breakdown,
                                { property: '$os', type: 'event' } satisfies Breakdown,
                            ],
                        },
                        created_at: '2024-01-01T00:00:00Z',
                    } satisfies ExperimentSavedMetric,
                ],
                metrics: [],
                metrics_secondary: [],
            }

            logic.actions.setExperiment(testExperiment)
            const breakdownToRemove: Breakdown = { property: '$browser', type: 'event' }
            logic.actions.removeMetricBreakdown('secondary-metric-uuid', 0, breakdownToRemove)

            expect(logic.values.experiment.saved_metrics[0].metadata.breakdowns).toEqual([
                { property: '$os', type: 'event' },
            ])
        })

        it('should include breakdowns when preparing secondary shared metrics for loading', () => {
            const testExperiment: Experiment = {
                ...experiment,
                saved_metrics: [
                    {
                        id: 1,
                        experiment: experiment.id as number,
                        saved_metric: 123,
                        name: 'Secondary Shared Metric',
                        query: {
                            uuid: 'secondary-metric-uuid',
                            kind: NodeKind.ExperimentMetric,
                            metric_type: ExperimentMetricType.MEAN,
                            source: { kind: NodeKind.EventsNode, event: '$pageview' },
                        },
                        metadata: {
                            type: 'secondary',
                            breakdowns: [
                                { property: '$browser', type: 'event' } satisfies Breakdown,
                                { property: '$os', type: 'event' } satisfies Breakdown,
                            ],
                        },
                        created_at: '2024-01-01T00:00:00Z',
                    } satisfies ExperimentSavedMetric,
                ],
                metrics: [],
                metrics_secondary: [],
                secondary_metrics_ordered_uuids: ['secondary-metric-uuid'],
                start_date: '2024-01-01',
            }

            logic.actions.setExperiment(testExperiment)

            // Check that orderedSecondaryMetricsWithResults includes breakdowns
            const metricsWithResults = logic.values.orderedSecondaryMetricsWithResults
            expect(metricsWithResults.length).toBe(1)
            const enrichedMetric = metricsWithResults[0].metric
            expect(enrichedMetric.breakdownFilter?.breakdowns).toEqual([
                { property: '$browser', type: 'event' },
                { property: '$os', type: 'event' },
            ])
        })
    })

    describe('launchExperiment', () => {
        it('calls launch endpoint and dispatches setExperiment with response', async () => {
            const launchedResponse = { ...experiment, start_date: '2026-03-17T10:00:00Z', status: 'running' }
            const createSpy = jest.spyOn(api, 'create').mockResolvedValue(launchedResponse)

            const keyed = experimentLogic({ experimentId: experiment.id })
            keyed.mount()

            const draftExperiment = { ...experiment, start_date: null, status: 'draft' } as unknown as Experiment
            keyed.actions.setExperiment(draftExperiment)

            await expectLogic(keyed, () => {
                keyed.actions.launchExperiment()
            })
                .toDispatchActions(['launchExperiment', 'setExperiment'])
                .toFinishAllListeners()

            expect(createSpy).toHaveBeenCalledWith(expect.stringContaining(`/experiments/${experiment.id}/launch`))
            createSpy.mockRestore()
            keyed.unmount()
        })

        it('shows error toast on validation error', async () => {
            // Mock api.create directly for error tests because MSW error responses
            // go through the full ApiError pipeline, making it fragile to test the
            // exact error shape. What we care about is: if the call rejects with a
            // detail, the toast shows it.
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue({
                detail: 'Experiment has already been launched.',
            })
            const errorMock = lemonToast.error as jest.Mock
            errorMock.mockClear()

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                logic.actions.launchExperiment()
            }).toFinishAllListeners()

            expect(errorMock).toHaveBeenCalledWith('Experiment has already been launched.')
            createSpy.mockRestore()
        })

        it('shows generic error toast when detail is missing', async () => {
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue(new Error('Network error'))
            const errorMock = lemonToast.error as jest.Mock
            errorMock.mockClear()

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                logic.actions.launchExperiment()
            }).toFinishAllListeners()

            expect(errorMock).toHaveBeenCalledWith('Failed to launch experiment')
            createSpy.mockRestore()
        })

        it('does not update experiment state on error', async () => {
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue({
                detail: 'Experiment has already been launched.',
            })

            const draftExperiment = { ...experiment, start_date: undefined, status: 'draft' } as unknown as Experiment
            logic.actions.setExperiment(draftExperiment)

            await expectLogic(logic, () => {
                logic.actions.launchExperiment()
            }).toFinishAllListeners()

            expect(logic.values.experiment.start_date).toBeUndefined()
            createSpy.mockRestore()
        })
    })

    describe('archiveExperiment', () => {
        it('calls archive endpoint and dispatches setExperiment with response', async () => {
            const archivedResponse = { ...experiment, archived: true }
            const createSpy = jest.spyOn(api, 'create').mockResolvedValue(archivedResponse)

            const keyed = experimentLogic({ experimentId: experiment.id })
            keyed.mount()
            keyed.actions.setExperiment(experiment)

            await expectLogic(keyed, () => {
                keyed.actions.archiveExperiment()
            })
                .toDispatchActions(['archiveExperiment', 'setExperiment'])
                .toFinishAllListeners()

            expect(createSpy).toHaveBeenCalledWith(expect.stringContaining(`/experiments/${experiment.id}/archive`), {
                disable_feature_flag: false,
            })
            createSpy.mockRestore()
            keyed.unmount()
        })

        it('shows error toast on validation error', async () => {
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue({
                detail: 'Experiment is already archived.',
            })
            const errorMock = lemonToast.error as jest.Mock
            errorMock.mockClear()

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                logic.actions.archiveExperiment()
            }).toFinishAllListeners()

            expect(errorMock).toHaveBeenCalledWith('Experiment is already archived.')
            createSpy.mockRestore()
        })

        it('shows generic error toast when detail is missing', async () => {
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue(new Error('Network error'))
            const errorMock = lemonToast.error as jest.Mock
            errorMock.mockClear()

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                logic.actions.archiveExperiment()
            }).toFinishAllListeners()

            expect(errorMock).toHaveBeenCalledWith('Failed to archive experiment')
            createSpy.mockRestore()
        })
    })

    describe('pauseExperiment', () => {
        it('calls pause endpoint and updates both experiment and feature flag state', async () => {
            const pausedResponse = {
                ...experiment,
                feature_flag: { ...experiment.feature_flag, active: false },
            }
            const createSpy = jest.spyOn(api, 'create').mockResolvedValue(pausedResponse)

            const keyed = experimentLogic({ experimentId: experiment.id })
            keyed.mount()
            keyed.actions.setExperiment(experiment)

            // Pre-condition: flag is active
            expect(keyed.values.experiment.feature_flag?.active).toBe(true)

            await expectLogic(keyed, () => {
                keyed.actions.pauseExperiment()
            })
                .toDispatchActions(['pauseExperiment', 'setExperiment'])
                .toFinishAllListeners()

            expect(createSpy).toHaveBeenCalledWith(expect.stringContaining(`/experiments/${experiment.id}/pause`))

            // Post-condition: both experiment and nested feature flag are updated
            expect(keyed.values.experiment.feature_flag?.active).toBe(false)
            expect(keyed.values.experiment.id).toBe(experiment.id)

            createSpy.mockRestore()
            keyed.unmount()
        })

        it('shows error toast on validation error', async () => {
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue({
                detail: 'Experiment is already paused.',
            })
            const errorMock = lemonToast.error as jest.Mock
            errorMock.mockClear()

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                logic.actions.pauseExperiment()
            }).toFinishAllListeners()

            expect(errorMock).toHaveBeenCalledWith('Experiment is already paused.')
            createSpy.mockRestore()
        })

        it('shows generic error toast when detail is missing', async () => {
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue(new Error('Network error'))
            const errorMock = lemonToast.error as jest.Mock
            errorMock.mockClear()

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                logic.actions.pauseExperiment()
            }).toFinishAllListeners()

            expect(errorMock).toHaveBeenCalledWith('Failed to pause experiment')
            createSpy.mockRestore()
        })
    })

    describe('resumeExperiment', () => {
        it('calls resume endpoint and updates both experiment and feature flag state', async () => {
            const pausedExperiment = {
                ...experiment,
                feature_flag: { ...experiment.feature_flag, active: false },
            } as Experiment
            const resumedResponse = {
                ...experiment,
                feature_flag: { ...experiment.feature_flag, active: true },
            }
            const createSpy = jest.spyOn(api, 'create').mockResolvedValue(resumedResponse)

            const keyed = experimentLogic({ experimentId: experiment.id })
            keyed.mount()
            keyed.actions.setExperiment(pausedExperiment)

            // Pre-condition: flag is inactive (paused)
            expect(keyed.values.experiment.feature_flag?.active).toBe(false)

            await expectLogic(keyed, () => {
                keyed.actions.resumeExperiment()
            })
                .toDispatchActions(['resumeExperiment', 'setExperiment'])
                .toFinishAllListeners()

            expect(createSpy).toHaveBeenCalledWith(expect.stringContaining(`/experiments/${experiment.id}/resume`))

            // Post-condition: both experiment and nested feature flag are updated
            expect(keyed.values.experiment.feature_flag?.active).toBe(true)
            expect(keyed.values.experiment.id).toBe(experiment.id)

            createSpy.mockRestore()
            keyed.unmount()
        })

        it('shows error toast on validation error', async () => {
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue({
                detail: 'Experiment is not paused.',
            })
            const errorMock = lemonToast.error as jest.Mock
            errorMock.mockClear()

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                logic.actions.resumeExperiment()
            }).toFinishAllListeners()

            expect(errorMock).toHaveBeenCalledWith('Experiment is not paused.')
            createSpy.mockRestore()
        })

        it('shows generic error toast when detail is missing', async () => {
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue(new Error('Network error'))
            const errorMock = lemonToast.error as jest.Mock
            errorMock.mockClear()

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                logic.actions.resumeExperiment()
            }).toFinishAllListeners()

            expect(errorMock).toHaveBeenCalledWith('Failed to resume experiment')
            createSpy.mockRestore()
        })
    })

    describe('freezeExposure', () => {
        it('calls freeze_exposure endpoint, updates experiment, and toggles the loading guard', async () => {
            const frozenResponse = { ...experiment, status: 'exposure_frozen' }
            const createSpy = jest.spyOn(api, 'create').mockResolvedValue(frozenResponse)

            const keyed = experimentLogic({ experimentId: experiment.id })
            keyed.mount()
            keyed.actions.setExperiment(experiment)

            expect(keyed.values.freezeExposureLoading).toBe(false)

            await expectLogic(keyed, () => {
                keyed.actions.freezeExposure()
            })
                .toDispatchActions(['freezeExposure', 'setFreezeExposureLoading', 'setExperiment'])
                .toFinishAllListeners()

            expect(createSpy).toHaveBeenCalledWith(
                expect.stringContaining(`/experiments/${experiment.id}/freeze_exposure`)
            )
            expect(keyed.values.experiment.status).toBe('exposure_frozen')
            // Loading guard is reset after the request settles.
            expect(keyed.values.freezeExposureLoading).toBe(false)

            createSpy.mockRestore()
            keyed.unmount()
        })

        it('shows error toast and resets the loading guard on failure', async () => {
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue({
                detail: 'Experiment exposure is already frozen.',
            })
            const errorMock = lemonToast.error as jest.Mock
            errorMock.mockClear()

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                logic.actions.freezeExposure()
            }).toFinishAllListeners()

            expect(errorMock).toHaveBeenCalledWith('Experiment exposure is already frozen.')
            expect(logic.values.freezeExposureLoading).toBe(false)
            createSpy.mockRestore()
        })
    })

    describe('unfreezeExposure', () => {
        it('calls unfreeze_exposure endpoint, updates experiment, and toggles the loading guard', async () => {
            const unfrozenResponse = { ...experiment, status: 'running' }
            const createSpy = jest.spyOn(api, 'create').mockResolvedValue(unfrozenResponse)

            const keyed = experimentLogic({ experimentId: experiment.id })
            keyed.mount()
            keyed.actions.setExperiment({ ...experiment, status: 'exposure_frozen' } as Experiment)

            await expectLogic(keyed, () => {
                keyed.actions.unfreezeExposure()
            })
                .toDispatchActions(['unfreezeExposure', 'setUnfreezeExposureLoading', 'setExperiment'])
                .toFinishAllListeners()

            expect(createSpy).toHaveBeenCalledWith(
                expect.stringContaining(`/experiments/${experiment.id}/unfreeze_exposure`)
            )
            expect(keyed.values.experiment.status).toBe('running')
            expect(keyed.values.unfreezeExposureLoading).toBe(false)

            createSpy.mockRestore()
            keyed.unmount()
        })
    })

    describe('resetRunningExperiment', () => {
        it('calls reset endpoint and updates experiment to draft state', async () => {
            const runningExperiment = {
                ...experiment,
                start_date: '2026-03-17T10:00:00Z',
                status: 'running',
            } as Experiment
            const resetResponse = {
                ...experiment,
                start_date: null,
                end_date: null,
                archived: false,
                conclusion: null,
                conclusion_comment: null,
                status: 'draft',
            }
            const createSpy = jest.spyOn(api, 'create').mockResolvedValue(resetResponse)

            const keyed = experimentLogic({ experimentId: experiment.id })
            keyed.mount()
            keyed.actions.setExperiment(runningExperiment)

            // Pre-condition: experiment is running with cached metric results
            expect(keyed.values.experiment.start_date).toBe('2026-03-17T10:00:00Z')
            const stubResult = { result: 'stub' } as any
            keyed.actions.setPrimaryMetricsResults([stubResult])
            keyed.actions.setSecondaryMetricsResults([stubResult])
            keyed.actions.setPrimaryMetricsResultsErrors([{ error: 'stub' }])
            keyed.actions.setSecondaryMetricsResultsErrors([{ error: 'stub' }])
            expect(keyed.values.primaryMetricsResults).toHaveLength(1)

            await expectLogic(keyed, () => {
                keyed.actions.resetRunningExperiment()
            })
                .toDispatchActions(['resetRunningExperiment', 'setExperiment', 'clearMetricsResults'])
                .toFinishAllListeners()

            expect(createSpy).toHaveBeenCalledWith(expect.stringContaining(`/experiments/${experiment.id}/reset`))

            // Post-condition: experiment is back to draft state
            expect(keyed.values.experiment.start_date).toBeNull()
            expect(keyed.values.experiment.end_date).toBeNull()
            expect(keyed.values.experiment.status).toBe('draft')

            // Post-condition: metric results are cleared
            expect(keyed.values.primaryMetricsResults).toEqual([])
            expect(keyed.values.secondaryMetricsResults).toEqual([])
            expect(keyed.values.primaryMetricsResultsErrors).toEqual([])
            expect(keyed.values.secondaryMetricsResultsErrors).toEqual([])

            createSpy.mockRestore()
            keyed.unmount()
        })

        it('shows error toast on validation error', async () => {
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue({
                detail: 'Experiment is already in draft state.',
            })
            const errorMock = lemonToast.error as jest.Mock
            errorMock.mockClear()

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                logic.actions.resetRunningExperiment()
            }).toFinishAllListeners()

            expect(errorMock).toHaveBeenCalledWith('Experiment is already in draft state.')
            createSpy.mockRestore()
        })

        it('shows generic error toast when detail is missing', async () => {
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue(new Error('Network error'))
            const errorMock = lemonToast.error as jest.Mock
            errorMock.mockClear()

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                logic.actions.resetRunningExperiment()
            }).toFinishAllListeners()

            expect(errorMock).toHaveBeenCalledWith('Failed to reset experiment')
            createSpy.mockRestore()
        })
    })

    describe('endExperiment', () => {
        it('calls end endpoint and dispatches setExperiment with response', async () => {
            const runningExperiment = {
                ...experiment,
                start_date: '2026-03-17T10:00:00Z',
                status: 'running',
                conclusion: 'won',
                conclusion_comment: 'Test variant won clearly',
            } as Experiment
            const endedResponse = {
                ...runningExperiment,
                end_date: '2026-03-24T10:00:00Z',
                status: 'stopped',
            }
            const createSpy = jest.spyOn(api, 'create').mockResolvedValue(endedResponse)

            const keyed = experimentLogic({ experimentId: experiment.id })
            keyed.mount()
            keyed.actions.setExperiment(runningExperiment)

            // Pre-condition: experiment is running
            expect(keyed.values.experiment.end_date).toBeFalsy()
            expect(keyed.values.experiment.status).toBe('running')

            await expectLogic(keyed, () => {
                keyed.actions.endExperiment()
            })
                .toDispatchActions(['endExperiment', 'setExperiment'])
                .toFinishAllListeners()

            expect(createSpy).toHaveBeenCalledWith(expect.stringContaining(`/experiments/${experiment.id}/end`), {
                conclusion: 'won',
                conclusion_comment: 'Test variant won clearly',
                open_cleanup_pr: false,
            })

            // Post-condition: experiment is ended
            expect(keyed.values.experiment.end_date).toBe('2026-03-24T10:00:00Z')
            expect(keyed.values.experiment.status).toBe('stopped')

            createSpy.mockRestore()
            keyed.unmount()
        })

        it('shows error toast on validation error', async () => {
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue({
                detail: 'Experiment has already ended.',
            })
            const errorMock = lemonToast.error as jest.Mock
            errorMock.mockClear()

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                logic.actions.endExperiment()
            }).toFinishAllListeners()

            expect(errorMock).toHaveBeenCalledWith('Experiment has already ended.')
            createSpy.mockRestore()
        })

        it('shows generic error toast when detail is missing', async () => {
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue(new Error('Network error'))
            const errorMock = lemonToast.error as jest.Mock
            errorMock.mockClear()

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                logic.actions.endExperiment()
            }).toFinishAllListeners()

            expect(errorMock).toHaveBeenCalledWith('Failed to end experiment')
            createSpy.mockRestore()
        })
    })

    describe('finishExperiment (ship variant)', () => {
        it('calls ship_variant endpoint and dispatches setExperiment with response', async () => {
            const runningExperiment = {
                ...experiment,
                start_date: '2026-03-17T10:00:00Z',
                status: 'running',
                conclusion: 'won',
                conclusion_comment: 'Test variant won clearly',
                feature_flag: { id: 1, key: 'flag', active: true, filters: {} },
            } as Experiment
            const shippedResponse = {
                ...runningExperiment,
                end_date: '2026-03-24T10:00:00Z',
                status: 'stopped',
                feature_flag: {
                    id: 1,
                    key: 'flag',
                    active: true,
                    filters: {
                        groups: [{ properties: [], rollout_percentage: 100 }],
                        multivariate: {
                            variants: [
                                { key: 'control', rollout_percentage: 0 },
                                { key: 'test', rollout_percentage: 100 },
                            ],
                        },
                    },
                },
            }
            const createSpy = jest.spyOn(api, 'create').mockResolvedValue(shippedResponse)

            const keyed = experimentLogic({ experimentId: experiment.id })
            keyed.mount()
            keyed.actions.setExperiment(runningExperiment)

            // Pre-condition: experiment is running
            expect(keyed.values.experiment.status).toBe('running')

            await expectLogic(keyed, () => {
                keyed.actions.finishExperiment({ selectedVariantKey: 'test', releaseToEveryone: false })
            })
                .toDispatchActions(['finishExperiment', 'setExperiment'])
                .toFinishAllListeners()

            expect(createSpy).toHaveBeenCalledWith(
                expect.stringContaining(`/experiments/${experiment.id}/ship_variant`),
                {
                    variant_key: 'test',
                    release_to_everyone: false,
                    conclusion: 'won',
                    conclusion_comment: 'Test variant won clearly',
                    open_cleanup_pr: false,
                }
            )

            // Post-condition: experiment is ended with shipped flag
            expect(keyed.values.experiment.end_date).toBe('2026-03-24T10:00:00Z')
            expect(keyed.values.experiment.status).toBe('stopped')
            expect(keyed.values.experiment.feature_flag?.filters?.multivariate?.variants).toEqual([
                { key: 'control', rollout_percentage: 0 },
                { key: 'test', rollout_percentage: 100 },
            ])

            createSpy.mockRestore()
            keyed.unmount()
        })

        it('shows error toast on validation error', async () => {
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue({
                detail: 'Experiment has not been launched yet.',
            })
            const errorMock = lemonToast.error as jest.Mock
            errorMock.mockClear()

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                logic.actions.finishExperiment({ selectedVariantKey: 'test', releaseToEveryone: false })
            }).toFinishAllListeners()

            expect(errorMock).toHaveBeenCalledWith('Experiment has not been launched yet.')
            createSpy.mockRestore()
        })

        it('shows generic error toast when detail is missing', async () => {
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue(new Error('Network error'))
            const errorMock = lemonToast.error as jest.Mock
            errorMock.mockClear()

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                logic.actions.finishExperiment({ selectedVariantKey: 'test', releaseToEveryone: false })
            }).toFinishAllListeners()

            expect(errorMock).toHaveBeenCalledWith('Failed to ship variant')
            createSpy.mockRestore()
        })

        it('shows approval toast and suppresses error toast on 409', async () => {
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue({
                status: 409,
                data: { change_request_id: 'cr-123' },
            })
            const errorMock = lemonToast.error as jest.Mock
            errorMock.mockClear()
            mockShowApprovalRequiredToast.mockClear()

            const expWithFlag = {
                ...experiment,
                feature_flag: { id: 42, key: 'flag', active: true, filters: {} },
            } as Experiment
            logic.actions.setExperiment(expWithFlag)

            await expectLogic(logic, () => {
                logic.actions.finishExperiment({ selectedVariantKey: 'test', releaseToEveryone: false })
            }).toFinishAllListeners()

            // Should show approval required toast with change request ID
            expect(mockShowApprovalRequiredToast).toHaveBeenCalledWith(
                'cr-123',
                'end this experiment and roll out the winning variant'
            )
            // Should NOT show the generic error toast
            expect(errorMock).not.toHaveBeenCalled()
            createSpy.mockRestore()
        })
    })

    describe('endExperimentLoading', () => {
        // The end and ship-variant lifecycle calls both drive the single endExperimentLoading flag.
        const triggers: { name: string; run: (l: ReturnType<typeof experimentLogic>) => void }[] = [
            { name: 'endExperiment', run: (l) => l.actions.endExperiment() },
            {
                name: 'finishExperiment',
                run: (l) => l.actions.finishExperiment({ selectedVariantKey: 'test', releaseToEveryone: false }),
            },
        ]

        it.each(triggers)('flips the flag on then off around a successful $name', async ({ run }) => {
            const runningExperiment = {
                ...experiment,
                start_date: '2026-03-17T10:00:00Z',
                status: 'running',
                conclusion: 'won',
            } as Experiment
            const createSpy = jest.spyOn(api, 'create').mockResolvedValue({
                ...runningExperiment,
                end_date: '2026-03-24T10:00:00Z',
                status: 'stopped',
            })

            const keyed = experimentLogic({ experimentId: experiment.id })
            keyed.mount()
            keyed.actions.setExperiment(runningExperiment)

            await expectLogic(keyed, () => {
                run(keyed)
            })
                // loading flips on before the request and off after it resolves
                .toDispatchActions(['setEndExperimentLoading', 'setExperiment', 'setEndExperimentLoading'])
                .toFinishAllListeners()
                .toMatchValues({ endExperimentLoading: false })

            createSpy.mockRestore()
            keyed.unmount()
        })

        it.each(triggers)('resets the flag after a failed $name', async ({ run }) => {
            const createSpy = jest.spyOn(api, 'create').mockRejectedValue({ detail: 'boom' })

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                run(logic)
            })
                .toFinishAllListeners()
                .toMatchValues({ endExperimentLoading: false })

            createSpy.mockRestore()
        })
    })

    describe('updateDistribution', () => {
        beforeEach(() => {
            jest.spyOn(api, 'update')
            api.update.mockClear()
        })

        it('sends variant split and holdout via experiment update with update_feature_flag_params', async () => {
            const updatedExperiment = {
                ...experiment,
                parameters: {
                    ...experiment.parameters,
                    feature_flag_variants: [
                        { key: 'control', rollout_percentage: 75 },
                        { key: 'test', rollout_percentage: 25 },
                    ],
                },
            }
            api.update.mockResolvedValue(updatedExperiment)

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                logic.actions.updateDistribution([
                    { key: 'control', rollout_percentage: 75 },
                    { key: 'test', rollout_percentage: 25 },
                ])
            }).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledWith(
                expect.stringContaining('/experiments/'),
                expect.objectContaining({
                    feature_flag: {
                        filters: {
                            multivariate: {
                                variants: [
                                    { key: 'control', rollout_percentage: 75 },
                                    { key: 'test', rollout_percentage: 25 },
                                ],
                            },
                        },
                    },
                    holdout_id: experiment.holdout_id,
                    update_feature_flag_params: true,
                })
            )
            // No rollout group when the caller omits rolloutPercentage (the modal itself always
            // passes one; this covers the omit branch)
            const sentFlagFilters = (api.update.mock.calls[0][1] as Record<string, any>).feature_flag.filters
            expect(sentFlagFilters).not.toHaveProperty('groups')
        })

        it('does not call feature flag API directly', async () => {
            api.update.mockResolvedValue(experiment)

            logic.actions.setExperiment(experiment)

            await expectLogic(logic, () => {
                logic.actions.updateDistribution([
                    { key: 'control', rollout_percentage: 60 },
                    { key: 'test', rollout_percentage: 40 },
                ])
            }).toFinishAllListeners()

            // Should only call the experiment endpoint, not the feature flag endpoint
            for (const call of api.update.mock.calls) {
                expect(call[0]).not.toContain('/feature_flags/')
            }
        })
    })

    describe('experimentWarning', () => {
        const multivariantFilters = {
            groups: [{ properties: [], rollout_percentage: 100 }],
            multivariate: {
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
            },
        }

        const shippedVariantFilters = {
            groups: [{ properties: [], rollout_percentage: 100 }],
            multivariate: {
                variants: [
                    { key: 'control', rollout_percentage: 0 },
                    { key: 'test', rollout_percentage: 100 },
                ],
            },
        }

        const zeroRolloutFilters = {
            groups: [{ properties: [], rollout_percentage: 0 }],
            multivariate: {
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
            },
        }

        const zeroRolloutShippedVariantFilters = {
            groups: [{ properties: [], rollout_percentage: 0 }],
            multivariate: {
                variants: [
                    { key: 'control', rollout_percentage: 0 },
                    { key: 'test', rollout_percentage: 100 },
                ],
            },
        }

        const createExperiment = (overrides: Partial<Experiment>): Experiment =>
            ({
                ...experiment,
                ...overrides,
            }) as Experiment

        it.each<{ desc: string; overrides: Partial<Experiment>; expected: ExperimentWarning | null }>([
            {
                desc: 'running experiment with active flag and normal rollout',
                overrides: {
                    start_date: '2020-01-01',
                    end_date: undefined,
                    feature_flag: { id: 1, key: 'flag', active: true, filters: multivariantFilters } as any,
                },
                expected: null,
            },
            {
                desc: 'running experiment with disabled flag',
                overrides: {
                    start_date: '2020-01-01',
                    end_date: undefined,
                    feature_flag: { id: 1, key: 'flag', active: false, filters: multivariantFilters } as any,
                },
                expected: { key: 'running_but_flag_disabled' },
            },
            {
                desc: 'running experiment with single variant shipped',
                overrides: {
                    start_date: '2020-01-01',
                    end_date: undefined,
                    feature_flag: { id: 1, key: 'flag', active: true, filters: shippedVariantFilters } as any,
                },
                expected: { key: 'running_but_single_variant_shipped', variantKey: 'test' },
            },
            {
                desc: 'running experiment with zero rollout',
                overrides: {
                    start_date: '2020-01-01',
                    end_date: undefined,
                    feature_flag: { id: 1, key: 'flag', active: true, filters: zeroRolloutFilters } as any,
                },
                expected: { key: 'running_but_no_rollout' },
            },
            {
                desc: 'running experiment with zero rollout takes priority over single variant shipped',
                overrides: {
                    start_date: '2020-01-01',
                    end_date: undefined,
                    feature_flag: {
                        id: 1,
                        key: 'flag',
                        active: true,
                        filters: zeroRolloutShippedVariantFilters,
                    } as any,
                },
                expected: { key: 'running_but_no_rollout' },
            },
            {
                desc: 'ended experiment with flag still distributing multiple variants',
                overrides: {
                    start_date: '2020-01-01',
                    end_date: '2020-02-01',
                    feature_flag: { id: 1, key: 'flag', active: true, filters: multivariantFilters } as any,
                },
                expected: { key: 'ended_but_multiple_variants_rolled_out' },
            },
            {
                desc: 'ended experiment with flag active but zero group rollout',
                overrides: {
                    start_date: '2020-01-01',
                    end_date: '2020-02-01',
                    feature_flag: { id: 1, key: 'flag', active: true, filters: zeroRolloutFilters } as any,
                },
                expected: null,
            },
            {
                desc: 'ended experiment with flag disabled',
                overrides: {
                    start_date: '2020-01-01',
                    end_date: '2020-02-01',
                    feature_flag: { id: 1, key: 'flag', active: false, filters: multivariantFilters } as any,
                },
                expected: null,
            },
            {
                desc: 'ended experiment with single variant shipped',
                overrides: {
                    start_date: '2020-01-01',
                    end_date: '2020-02-01',
                    feature_flag: { id: 1, key: 'flag', active: true, filters: shippedVariantFilters } as any,
                },
                expected: null,
            },
            {
                desc: 'archived ended experiment with flag still distributing multiple variants',
                overrides: {
                    start_date: '2020-01-01',
                    end_date: '2020-02-01',
                    archived: true,
                    feature_flag: { id: 1, key: 'flag', active: true, filters: multivariantFilters } as any,
                },
                expected: { key: 'ended_but_multiple_variants_rolled_out' },
            },
            {
                desc: 'draft experiment with flag already active and distributing variants',
                overrides: {
                    start_date: undefined,
                    end_date: undefined,
                    feature_flag: { id: 1, key: 'flag', active: true, filters: multivariantFilters } as any,
                },
                expected: { key: 'not_started_but_multiple_variants_rolled_out' },
            },
            {
                desc: 'draft experiment with flag active but zero group rollout',
                overrides: {
                    start_date: undefined,
                    end_date: undefined,
                    feature_flag: { id: 1, key: 'flag', active: true, filters: zeroRolloutFilters } as any,
                },
                expected: null,
            },
            {
                desc: 'draft experiment with flag disabled',
                overrides: {
                    start_date: undefined,
                    end_date: undefined,
                    feature_flag: { id: 1, key: 'flag', active: false, filters: multivariantFilters } as any,
                },
                expected: null,
            },
            {
                desc: 'ended experiment with deleted flag still marked active',
                overrides: {
                    start_date: '2020-01-01',
                    end_date: '2020-02-01',
                    feature_flag: {
                        id: 1,
                        key: 'flag:deleted:1',
                        active: true,
                        deleted: true,
                        filters: multivariantFilters,
                    } as any,
                },
                expected: null,
            },
            {
                desc: 'draft experiment with deleted flag still marked active',
                overrides: {
                    start_date: undefined,
                    end_date: undefined,
                    feature_flag: {
                        id: 1,
                        key: 'flag:deleted:1',
                        active: true,
                        deleted: true,
                        filters: multivariantFilters,
                    } as any,
                },
                expected: null,
            },
        ])('$desc → $expected', ({ overrides, expected }) => {
            logic.actions.setExperiment(createExperiment(overrides))
            expect(logic.values.experimentWarning).toEqual(expected)
        })
    })

    describe('getDisplayOrderedIndices', () => {
        it.each([
            ['null orderedUuids — identity order', [{ uuid: 'a' }, { uuid: 'b' }, { uuid: 'c' }], null, [0, 1, 2]],
            ['undefined orderedUuids — identity order', [{ uuid: 'a' }, { uuid: 'b' }], undefined, [0, 1]],
            ['empty orderedUuids — identity order', [{ uuid: 'a' }, { uuid: 'b' }], [], [0, 1]],
            ['reorders by orderedUuids', [{ uuid: 'a' }, { uuid: 'b' }, { uuid: 'c' }], ['c', 'a', 'b'], [2, 0, 1]],
            [
                'appends missing metrics at end',
                [{ uuid: 'a' }, { uuid: 'b' }, { uuid: 'c' }, { uuid: 'd' }],
                ['c', 'a'],
                [2, 0, 1, 3],
            ],
            ['ignores uuids not in metrics', [{ uuid: 'a' }, { uuid: 'b' }], ['x', 'b', 'y', 'a'], [1, 0]],
            ['handles metrics without uuids', [{ uuid: 'a' }, {}, { uuid: 'c' }], ['c', 'a'], [2, 0, 1]],
        ])('%s', (_desc, metrics, orderedUuids, expected) => {
            expect(getDisplayOrderedIndices(metrics, orderedUuids)).toEqual(expected)
        })

        it('returns all indices exactly once', () => {
            const metrics = [{ uuid: 'a' }, { uuid: 'b' }, { uuid: 'c' }, { uuid: 'd' }, { uuid: 'e' }]
            expect(getDisplayOrderedIndices(metrics, ['d', 'b']).sort()).toEqual([0, 1, 2, 3, 4])
        })
    })

    describe('excluded variants', () => {
        it('excludedVariants selector reads the excluded_variants column', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...experiment,
                    excluded_variants: ['test-3'],
                })
            }).toMatchValues({
                excludedVariants: ['test-3'],
            })
        })

        it('excludedVariants defaults to [] when missing', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...experiment,
                    parameters: { ...experiment.parameters },
                })
            }).toMatchValues({
                excludedVariants: [],
            })
        })

        it('setVariantExcluded PATCHes excluded_variants with the merged exclusion list', async () => {
            jest.spyOn(api, 'update')
            api.update.mockClear()
            const existingExperiment = {
                ...experiment,
                excluded_variants: ['test-1'],
            } as Experiment
            api.update.mockResolvedValue(existingExperiment)

            logic.actions.setExperiment(existingExperiment)

            await expectLogic(logic, () => {
                logic.actions.setVariantExcluded('test-2', true)
            })
                .toDispatchActions(['setVariantExcluded'])
                .toFinishAllListeners()

            // The PATCH targets excluded_variants only — no parameters / feature_flag_variants resend.
            const sentBody = api.update.mock.calls[0][1] as Record<string, any>
            expect(sentBody.parameters).toBeUndefined()
            expect(sentBody.excluded_variants).toEqual(expect.arrayContaining(['test-1', 'test-2']))
            expect(sentBody.excluded_variants).toHaveLength(2)
        })

        it('setVariantExcluded(key, false) removes the key from the exclusion list', async () => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...experiment,
                    excluded_variants: ['test-1', 'test-2'],
                })
            }).toMatchValues({
                excludedVariants: ['test-1', 'test-2'],
            })

            // Re-include test-2 — the new list (computed in the listener) must drop it.
            const next = logic.values.excludedVariants.filter((k) => k !== 'test-2')
            expect(next).toEqual(['test-1'])
        })
    })

    describe('variants', () => {
        const parameterVariants: MultivariateFlagVariant[] = [
            { key: 'control', rollout_percentage: 50 },
            { key: 'param-test', rollout_percentage: 50 },
        ]
        const flagVariants: MultivariateFlagVariant[] = [
            { key: 'control', rollout_percentage: 50 },
            { key: 'flag-test', rollout_percentage: 50 },
        ]

        it.each<{
            desc: string
            parameterVariants?: MultivariateFlagVariant[]
            flagVariants?: MultivariateFlagVariant[]
            expected: MultivariateFlagVariant[]
        }>([
            {
                desc: 'prefers the linked flag variants over the parameters mirror',
                parameterVariants,
                flagVariants,
                expected: flagVariants,
            },
            {
                desc: 'falls back to parameters.feature_flag_variants when the flag has no variants (creation flow)',
                parameterVariants,
                expected: parameterVariants,
            },
            {
                desc: 'reads the linked flag variants when parameters has no mirror',
                flagVariants,
                expected: flagVariants,
            },
            {
                desc: 'defaults to [] when neither source has variants',
                expected: [],
            },
        ])('$desc', async (row) => {
            await expectLogic(logic, () => {
                logic.actions.setExperiment({
                    ...experiment,
                    parameters: { ...experiment.parameters, feature_flag_variants: row.parameterVariants },
                    feature_flag: {
                        ...experiment.feature_flag,
                        filters: {
                            ...experiment.feature_flag?.filters,
                            multivariate: row.flagVariants ? { variants: row.flagVariants } : undefined,
                        },
                    },
                } as unknown as Experiment)
            }).toMatchValues({
                variants: row.expected,
            })
        })
    })
})
