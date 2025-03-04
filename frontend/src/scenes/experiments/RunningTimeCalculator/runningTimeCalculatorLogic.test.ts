import { expectLogic } from 'kea-test-utils'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { ExperimentMetric, ExperimentMetricType } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FeatureFlagBasicType } from '~/types'

import { runningTimeCalculatorLogic } from './runningTimeCalculatorLogic'

describe('runningTimeCalculatorLogic', () => {
    let logic: ReturnType<typeof runningTimeCalculatorLogic.build>

    beforeEach(() => {
        initKeaTests()
        experimentLogic.mount()

        logic = runningTimeCalculatorLogic()
        logic.mount()
    })

    // Should match https://docs.google.com/spreadsheets/d/11alyC8n7uqewZFLKfV4UAbW-0zH__EdV_Hrk2OQ4140/edit?gid=777532876#gid=777532876
    describe('calculations for COUNT', () => {
        beforeEach(() => {
            experimentLogic.actions.setExperiment({
                metrics: [
                    {
                        metric_type: ExperimentMetricType.COUNT,
                    } as ExperimentMetric,
                ],
                feature_flag: {
                    filters: {
                        multivariate: {
                            variants: [
                                {
                                    key: 'control',
                                    rollout_percentage: 50,
                                },
                                {
                                    key: 'test',
                                    rollout_percentage: 50,
                                },
                            ],
                        },
                    },
                } as unknown as FeatureFlagBasicType,
            })

            logic.actions.setMetricIndex(0)
        })

        it('calculates recommended sample size and running time correctly for COUNT', async () => {
            logic.actions.setMinimumDetectableEffect(5)
            logic.actions.setMetricResult({
                uniqueUsers: 14000,
                averageEventsPerUser: 4,
            })

            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                minimumDetectableEffect: 5,
                variance: 8,
                recommendedSampleSize: expect.closeTo(6400, 0),
                recommendedRunningTime: expect.closeTo(6.4, 1),
            })
        })
    })

    // Should match https://docs.google.com/spreadsheets/d/11alyC8n7uqewZFLKfV4UAbW-0zH__EdV_Hrk2OQ4140/edit?gid=2067479228#gid=2067479228
    describe('calculations for CONTINUOUS', () => {
        beforeEach(() => {
            experimentLogic.actions.setExperiment({
                metrics: [
                    {
                        metric_type: ExperimentMetricType.CONTINUOUS,
                    } as ExperimentMetric,
                ],
                feature_flag: {
                    filters: {
                        multivariate: {
                            variants: [
                                {
                                    key: 'control',
                                    rollout_percentage: 50,
                                },
                                {
                                    key: 'test',
                                    rollout_percentage: 50,
                                },
                            ],
                        },
                    },
                } as unknown as FeatureFlagBasicType,
            })

            logic.actions.setMetricIndex(0)
        })

        it('calculates recommended sample size and running time correctly for CONTINUOUS', async () => {
            logic.actions.setMinimumDetectableEffect(5)
            logic.actions.setMetricResult({
                uniqueUsers: 14000,
                averagePropertyValuePerUser: 50,
            })

            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                minimumDetectableEffect: 5,
                variance: expect.closeTo(625, 0),
                recommendedSampleSize: expect.closeTo(3200, 0),
                recommendedRunningTime: expect.closeTo(3.2, 1),
            })
        })
    })
})
