import { expectLogic } from 'kea-test-utils'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { experimentLogic, percentageDistribution } from './experimentLogic'

const RUNNING_EXP_ID = 45
const RUNNING_FUNNEL_EXP_ID = 46

describe('experimentLogic', () => {
    let logic: ReturnType<typeof experimentLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/experiments': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [{ id: 1, name: 'Test Exp', description: 'bla' }],
                },
                '/api/projects/:team/experiments/:id': {
                    created_at: '2022-01-13T12:44:45.944423Z',
                    created_by: { id: 1, uuid: '017dc2ea-ace1-0000-c9ed-a6e43fd8956b' },
                    description: 'badum tssss',
                    feature_flag_key: 'test-experiment',
                    filters: {
                        events: [{ id: 'user signup', name: 'user signup', type: 'events', order: 0 }],
                        insight: 'FUNNELS',
                    },
                    id: RUNNING_EXP_ID,
                    name: 'test experiment',
                    parameters: {
                        feature_flag_variants: [
                            { key: 'control', rollout_percentage: 25 },
                            { key: 'test_1', rollout_percentage: 25 },
                            { key: 'test_2', rollout_percentage: 25 },
                            { key: 'test_3', rollout_percentage: 25 },
                        ],
                        recommended_running_time: 20.2,
                        recommended_sample_size: 2930,
                    },
                    start_date: '2022-01-13T13:25:29.896000Z',
                    updated_at: '2022-01-13T13:25:38.462106Z',
                },
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

    describe('selector values', () => {
        it('given an mde, calculates correct sample size', async () => {
            await expectLogic(logic).toMatchValues({
                minimumDetectableEffect: 1,
            })

            expect(logic.values.minimumSampleSizePerVariant(20)).toEqual(25600)

            expect(logic.values.minimumSampleSizePerVariant(40)).toEqual(38400)

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
            expect(logic.values.recommendedExposureForCountData(1000)).toEqual(2251.2)

            // 10,000 entrants over 14 days
            // 10x entrants, so 1/10th running time
            expect(logic.values.recommendedExposureForCountData(10000)).toEqual(225.1)

            // 0 entrants over 14 days, so infinite running time
            expect(logic.values.recommendedExposureForCountData(0)).toEqual(Infinity)
        })
    })

    describe('percentageDistribution', () => {
        it('given variant count, calculates correct rollout percentages', async () => {
            expect(percentageDistribution(1)).toEqual([100])
            expect(percentageDistribution(2)).toEqual([50, 50])
            expect(percentageDistribution(3)).toEqual([33, 33, 34])
            expect(percentageDistribution(4)).toEqual([25, 25, 25, 25])
            expect(percentageDistribution(5)).toEqual([20, 20, 20, 20, 20])
            expect(percentageDistribution(6)).toEqual([17, 17, 17, 17, 17, 15])
            expect(percentageDistribution(7)).toEqual([14, 14, 14, 14, 14, 14, 16])
            expect(percentageDistribution(8)).toEqual([13, 13, 13, 13, 13, 13, 13, 9])
            expect(percentageDistribution(9)).toEqual([11, 11, 11, 11, 11, 11, 11, 11, 12])
            expect(percentageDistribution(10)).toEqual([10, 10, 10, 10, 10, 10, 10, 10, 10, 10])
            expect(percentageDistribution(11)).toEqual([9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 10])
            expect(percentageDistribution(12)).toEqual([8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 12])
            expect(percentageDistribution(13)).toEqual([8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 4])
            expect(percentageDistribution(14)).toEqual([7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 9])
            expect(percentageDistribution(15)).toEqual([7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 2])
            expect(percentageDistribution(16)).toEqual([6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 10])
            expect(percentageDistribution(17)).toEqual([6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 4])
            expect(percentageDistribution(18)).toEqual([6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, -2])
            expect(percentageDistribution(19)).toEqual([5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 10])
            expect(percentageDistribution(20)).toEqual([5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5])
        })
    })
})
