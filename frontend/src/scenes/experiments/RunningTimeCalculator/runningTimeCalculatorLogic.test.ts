import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { runningTimeCalculatorLogic } from './runningTimeCalculatorLogic'

describe('runningTimeCalculatorLogic', () => {
    let logic: ReturnType<typeof runningTimeCalculatorLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = runningTimeCalculatorLogic()
        logic.mount()
    })

    // Should match https://docs.google.com/spreadsheets/d/11alyC8n7uqewZFLKfV4UAbW-0zH__EdV_Hrk2OQ4140/edit?gid=777532876#gid=777532876
    describe('selectors', () => {
        it('calculates recommended sample size correctly', async () => {
            logic.actions.setMinimumDetectableEffect(5)
            logic.actions.setMetricResult({
                uniqueUsers: 28000,
                averageEventsPerUser: 4,
            })

            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                minimumDetectableEffect: 5,
                variance: 8,
                recommendedSampleSize: expect.closeTo(12800, 0),
            })
        })

        it('calculates recommended running time correctly', async () => {
            logic.actions.setMinimumDetectableEffect(5)
            logic.actions.setMetricResult({
                uniqueUsers: 28000,
                averageEventsPerUser: 4,
            })

            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                recommendedRunningTime: expect.closeTo(6.4, 1),
            })
        })
    })
})
