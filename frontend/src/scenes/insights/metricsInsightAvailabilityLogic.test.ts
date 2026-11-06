import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { metricsHasRecentMetricsRetrieve } from 'products/metrics/frontend/generated/api'
import { canViewMetrics } from 'products/metrics/frontend/metricsAccess'

import { metricsInsightAvailabilityLogic } from './metricsInsightAvailabilityLogic'

jest.mock('products/metrics/frontend/metricsAccess', () => ({ canViewMetrics: jest.fn() }))
jest.mock('products/metrics/frontend/generated/api', () => ({ metricsHasRecentMetricsRetrieve: jest.fn() }))

const BOTH_FLAGS = [FEATURE_FLAGS.METRICS, FEATURE_FLAGS.METRICS_INSIGHT_BUILDER]

describe('metricsInsightAvailabilityLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.mocked(canViewMetrics).mockReturnValue(true)
    })

    it.each([
        { flags: BOTH_FLAGS, response: { hasRecentMetrics: true }, checks: true, shown: true },
        { flags: BOTH_FLAGS, response: { hasRecentMetrics: false }, checks: true, shown: false },
        { flags: BOTH_FLAGS, response: new Error('network down'), checks: true, shown: false },
        { flags: [FEATURE_FLAGS.METRICS], response: { hasRecentMetrics: true }, checks: false, shown: false },
    ])('flags=$flags response=$response shows=$shown', async ({ flags, response, checks, shown }) => {
        const retrieve = jest.mocked(metricsHasRecentMetricsRetrieve)
        retrieve.mockReset()
        if (response instanceof Error) {
            retrieve.mockRejectedValue(response)
        } else {
            retrieve.mockResolvedValue(response)
        }
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))

        const logic = metricsInsightAvailabilityLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(retrieve).toHaveBeenCalledTimes(checks ? 1 : 0)
        expect(logic.values.showMetricsInsight).toBe(shown)
    })
})
