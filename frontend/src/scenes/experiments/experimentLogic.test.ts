import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import experimentJson from '~/mocks/fixtures/api/experiments/_experiment_launched_with_funnel_and_trends.json'
import experimentMetricResultsErrorJson from '~/mocks/fixtures/api/experiments/_experiment_metric_results_error.json'
import experimentMetricResultsSuccessJson from '~/mocks/fixtures/api/experiments/_experiment_metric_results_success.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment } from '~/types'

import { experimentLogic } from './experimentLogic'

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
                    '/api/environments/:team/query': (() => {
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
                    '/api/environments/:team/query': (() => {
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
                        },
                        null,
                    ],
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
    describe('pause and resume experiment', () => {
        beforeEach(() => {
            jest.spyOn(api, 'update')
            jest.spyOn(api, 'get')
            api.update.mockClear()
            api.get.mockClear()

            const experimentWithFlag = {
                ...experiment,
                feature_flag: { id: 123, key: 'test-flag', active: true },
            } as Experiment
            logic.actions.setExperiment(experimentWithFlag)
        })

        it('should pause experiment by disabling feature flag', async () => {
            api.update.mockResolvedValue({ id: 123, key: 'test-flag', active: false })

            await expectLogic(logic, () => {
                logic.actions.pauseExperiment()
            })
                .toDispatchActions(['pauseExperiment'])
                .toFinishAllListeners()

            expect(api.update).toHaveBeenCalledWith(
                expect.stringContaining('/feature_flags/123'),
                expect.objectContaining({ active: false })
            )
        })

        it('should resume experiment by enabling feature flag', async () => {
            const experimentWithInactiveFlag = {
                ...experiment,
                feature_flag: { id: 123, key: 'test-flag', active: false },
            } as Experiment
            logic.actions.setExperiment(experimentWithInactiveFlag)

            api.update.mockResolvedValue({ id: 123, key: 'test-flag', active: true })

            await expectLogic(logic, () => {
                logic.actions.resumeExperiment()
            })
                .toDispatchActions(['resumeExperiment'])
                .toFinishAllListeners()

            expect(api.update).toHaveBeenCalledWith(
                expect.stringContaining('/feature_flags/123'),
                expect.objectContaining({ active: true })
            )
        })

        it('should reload experiment after pause/resume', async () => {
            api.update.mockResolvedValue({ id: 123, key: 'test-flag', active: false })

            // The experiment will be reloaded via loadExperiment action
            // which uses the GET endpoint already set up in useMocks
            await expectLogic(logic, () => {
                logic.actions.pauseExperiment()
            })
                .toDispatchActions(['pauseExperiment', 'loadExperiment'])
                .toFinishAllListeners()

            // Verify that loadExperiment was called which will fetch the experiment again
            expect(logic.values.experiment).not.toBeNull()
        })
    })
})
