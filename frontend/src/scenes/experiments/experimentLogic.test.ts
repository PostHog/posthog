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

    describe('loadMetricResults', () => {
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

            const promise = logic.asyncActions.loadMetricResults(true)

            await expectLogic(logic).toDispatchActions(['setMetricResultsLoading', 'setMetricResults']).toMatchValues({
                metricResults: [],
                metricResultsLoading: true,
                primaryMetricsResultErrors: [],
            })

            await promise

            await expectLogic(logic)
                .toDispatchActions(['setMetricResultsLoading'])
                .toMatchValues({
                    metricResults: [
                        {
                            ...experimentMetricResultsSuccessJson.query_status.results,
                            fakeInsightId: expect.any(String),
                        },
                        null,
                    ],
                    metricResultsLoading: false,
                    primaryMetricsResultErrors: [
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

    describe('loadSecondaryMetricResults', () => {
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

            const promise = logic.asyncActions.loadSecondaryMetricResults(true)

            await expectLogic(logic)
                .toDispatchActions(['setSecondaryMetricResultsLoading', 'setSecondaryMetricResults'])
                .toMatchValues({
                    secondaryMetricResults: [],
                    secondaryMetricResultsLoading: true,
                    secondaryMetricsResultErrors: [],
                })

            await promise

            await expectLogic(logic)
                .toDispatchActions(['setSecondaryMetricResultsLoading'])
                .toMatchValues({
                    secondaryMetricResults: [
                        null,
                        {
                            ...experimentMetricResultsSuccessJson.query_status.results,
                            fakeInsightId: expect.any(String),
                        },
                    ],
                    secondaryMetricResultsLoading: false,
                    secondaryMetricsResultErrors: [
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

    describe('selector values', () => {
        it('given an mde, calculates correct sample size', async () => {
            await expectLogic(logic).toMatchValues({
                minimumDetectableEffect: 30,
            })

            expect(logic.values.minimumSampleSizePerVariant(20)).toEqual(29)

            expect(logic.values.minimumSampleSizePerVariant(40)).toEqual(43)

            expect(logic.values.minimumSampleSizePerVariant(0)).toEqual(0)
        })

        it('given sample size and entrants, calculates correct running time', async () => {
            // 500 entrants over 14 days, 1000 sample size, so need twice the time
            expect(logic.values.expectedRunningTime(500, 1000)).toEqual(28)

            // 500 entrants over 14 days, 250 sample size, so need half the time
            expect(logic.values.expectedRunningTime(500, 250)).toEqual(7)

            // 0 entrants over 14 days, so infinite running time
            expect(logic.values.expectedRunningTime(0, 1000)).toEqual(Infinity)
        })

        it('given control count data, calculates correct running time', async () => {
            // 1000 count over 14 days
            expect(logic.values.recommendedExposureForCountData(1000)).toEqual(2.8)

            // 10,000 entrants over 14 days
            // 10x entrants, so 1/10th running time
            expect(logic.values.recommendedExposureForCountData(10000)).toEqual(0.3)

            // 0 entrants over 14 days, so infinite running time
            expect(logic.values.recommendedExposureForCountData(0)).toEqual(Infinity)
        })
    })
})
