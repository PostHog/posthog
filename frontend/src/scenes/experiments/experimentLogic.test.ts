import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { userLogic } from 'scenes/userLogic'

import experimentJson from '~/mocks/fixtures/api/experiments/_experiment_launched_with_funnel_and_trends.json'
import experimentMetricResultsErrorJson from '~/mocks/fixtures/api/experiments/_experiment_metric_results_error.json'
import experimentMetricResultsSuccessJson from '~/mocks/fixtures/api/experiments/_experiment_metric_results_success.json'
import { useMocks } from '~/mocks/jest'
import { Breakdown, ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { Experiment } from '~/types'

import {
    ExperimentSavedMetric,
    ExperimentWarning,
    classifyError,
    experimentLogic,
    extractErrorDetailString,
    getDisplayOrderedIndices,
} from './experimentLogic'

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

            await expectLogic(logic)
                .toDispatchActions(['setPrimaryMetricsResultsLoading', 'setLegacyPrimaryMetricsResults'])
                .toMatchValues({
                    legacyPrimaryMetricsResults: [],
                    primaryMetricsResultsLoading: true,
                    primaryMetricsResultsErrors: [],
                })

            await promise

            await expectLogic(logic)
                .toDispatchActions(['setPrimaryMetricsResultsLoading'])
                .toMatchValues({
                    legacyPrimaryMetricsResults: [
                        {
                            ...experimentMetricResultsSuccessJson.query_status.results,
                            fakeInsightId: expect.any(String),
                        },
                        null,
                    ],
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

            await expectLogic(logic)
                .toDispatchActions(['setSecondaryMetricsResultsLoading', 'setLegacySecondaryMetricsResults'])
                .toMatchValues({
                    legacySecondaryMetricsResults: [],
                    secondaryMetricsResultsLoading: true,
                    secondaryMetricsResultsErrors: [],
                })

            await promise

            await expectLogic(logic)
                .toDispatchActions(['setSecondaryMetricsResultsLoading'])
                .toMatchValues({
                    legacySecondaryMetricsResults: [
                        null,
                        {
                            ...experimentMetricResultsSuccessJson.query_status.results,
                            fakeInsightId: expect.any(String),
                        },
                    ],
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

            expect(logic.values.primaryMetricsResultsLoading).toBe(false)
            expect(logic.values.secondaryMetricsResultsLoading).toBe(false)

            const successfulCount =
                logic.values.legacyPrimaryMetricsResults.filter(Boolean).length +
                logic.values.primaryMetricsResults.filter(Boolean).length +
                logic.values.legacySecondaryMetricsResults.filter(Boolean).length +
                logic.values.secondaryMetricsResults.filter(Boolean).length

            expect(successfulCount).toBeGreaterThan(0)
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

            expect(createSpy).toHaveBeenCalledWith(expect.stringContaining(`/experiments/${experiment.id}/archive`))
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
                keyed.actions.finishExperiment({ selectedVariantKey: 'test' })
            })
                .toDispatchActions(['finishExperiment', 'setExperiment'])
                .toFinishAllListeners()

            expect(createSpy).toHaveBeenCalledWith(
                expect.stringContaining(`/experiments/${experiment.id}/ship_variant`),
                {
                    variant_key: 'test',
                    conclusion: 'won',
                    conclusion_comment: 'Test variant won clearly',
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
                logic.actions.finishExperiment({ selectedVariantKey: 'test' })
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
                logic.actions.finishExperiment({ selectedVariantKey: 'test' })
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
                logic.actions.finishExperiment({ selectedVariantKey: 'test' })
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
                    parameters: expect.objectContaining({
                        feature_flag_variants: [
                            { key: 'control', rollout_percentage: 75 },
                            { key: 'test', rollout_percentage: 25 },
                        ],
                    }),
                    holdout_id: experiment.holdout_id,
                    update_feature_flag_params: true,
                })
            )
            // Should not send rollout_percentage — it's not editable in the distribution modal
            const sentParams = (api.update.mock.calls[0][1] as Record<string, any>).parameters
            expect(sentParams).not.toHaveProperty('rollout_percentage')
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

    describe('classifyError', () => {
        it.each([
            // [description, errorDetail, errorMessage, errorCode, statusCode, expected]
            ['504 gateway timeout', null, null, null, 504, 'timeout'],
            ['408 request timeout', null, null, null, 408, 'timeout'],
            ['query timeout body marker', 'Query timed out', null, null, 200, 'timeout'],
            ['memory-limit error code', null, null, 'memory_limit_exceeded', 500, 'out_of_memory'],
            ['OOM message pattern', null, 'Memory limit exceeded while running', null, 500, 'out_of_memory'],
            ['generic 500', null, null, null, 500, 'server_error'],
            ['503 unavailable', null, null, null, 503, 'server_error'],
            ['status 0 is network', null, null, null, 0, 'network_error'],
            ['TypeError: Failed to fetch', null, 'TypeError: Failed to fetch', null, null, 'network_error'],
            ['TypeError: Load failed', null, 'TypeError: Load failed', null, null, 'network_error'],
            [
                "TypeError: Failed to execute 'fetch'",
                null,
                "TypeError: Failed to execute 'fetch' on 'Window'",
                null,
                null,
                'network_error',
            ],
            ['NetworkError with null status', null, 'NetworkError when fetching', null, null, 'network_error'],
            ['404 not_found', null, 'Experiment with id 123 not found', 'not_found', 404, 'not_found'],
            ['401 unauthenticated', null, null, null, 401, 'authentication'],
            ['403 not_authenticated code', null, null, 'not_authenticated', 403, 'authentication'],
            ['403 permission_denied', null, null, 'permission_denied', 403, 'authorization'],
            ['plain 403', null, null, null, 403, 'authorization'],
            ['400 parse_error', null, null, 'parse_error', 400, 'validation_error'],
            ['400 invalid_input', null, null, 'invalid_input', 400, 'validation_error'],
            ['null status, no marker', null, 'Something odd', null, null, 'unknown'],
            ['418 teapot falls through', null, null, null, 418, 'unknown'],
        ] as const)('%s', (_desc, errorDetail, errorMessage, errorCode, statusCode, expected) => {
            expect(classifyError(errorDetail, errorMessage, errorCode, statusCode)).toEqual(expected)
        })

        it('prefers timeout over 5xx server_error (504 overlap)', () => {
            expect(classifyError(null, null, null, 504)).toEqual('timeout')
        })

        it('prefers out_of_memory over generic server_error', () => {
            expect(classifyError(null, null, 'query_memory_limit_exceeded', 500)).toEqual('out_of_memory')
        })

        it('does not treat fetch-style messages as network errors when an HTTP status was returned', () => {
            // A 400 response whose body happens to mention "Failed to fetch" should still classify by status, not network.
            expect(classifyError(null, 'Failed to fetch remote config', null, 400)).toEqual('validation_error')
        })
    })

    describe('extractErrorDetailString', () => {
        it.each([
            ['null → null', null, null],
            ['undefined → null', undefined, null],
            ['string passes through', 'Experiment with id 79259 not found', 'Experiment with id 79259 not found'],
            ['DRF {detail: "..."} unwraps the inner string', { detail: 'Not found.' }, 'Not found.'],
            [
                'object without string detail falls back to JSON',
                { 'no-exposures': true, 'no-control-variant': false },
                '{"no-exposures":true,"no-control-variant":false}',
            ],
            [
                'nested detail that is not a string falls back to JSON',
                { detail: { nested: 1 } },
                '{"detail":{"nested":1}}',
            ],
            ['array falls back to JSON', [1, 2, 3], '[1,2,3]'],
        ] as const)('%s', (_desc, input, expected) => {
            expect(extractErrorDetailString(input)).toEqual(expected)
        })

        it('returns null for values that cannot be stringified (circular refs)', () => {
            const circular: Record<string, unknown> = {}
            circular.self = circular
            expect(extractErrorDetailString(circular)).toBeNull()
        })
    })
})
