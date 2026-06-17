import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { projectLogic } from 'scenes/projectLogic'

import experimentJson from '~/mocks/fixtures/api/experiments/_experiment_launched_with_funnel_and_trends.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment } from '~/types'

import { experimentMetricsLogic } from './experimentMetricsLogic'
import { experimentResultsNotificationLogic } from './experimentResultsNotificationLogic'

const EXPERIMENT = experimentJson as unknown as Experiment
const OFFER_DELAY_MS = 10_000

describe('experimentResultsNotificationLogic', () => {
    let logic: ReturnType<typeof experimentResultsNotificationLogic.build>
    let metricsLogic: ReturnType<typeof experimentMetricsLogic.build>

    beforeEach(async () => {
        // Latest returns a completed run so the metrics logic's afterMount settles to a stable
        // terminal (isRecalculating=false) state — the tests then drive transitions deterministically.
        useMocks({
            get: {
                '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [
                    200,
                    {
                        id: 'seed',
                        status: 'completed',
                        total_metrics: 0,
                        completed_metrics: 0,
                        failed_metrics: 0,
                        completed_at: new Date().toISOString(),
                        results: [],
                    },
                ],
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION], {
            [FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION]: true,
        })
        await expectLogic(projectLogic).toMatchValues({ currentProjectId: expect.any(Number) })

        metricsLogic = experimentMetricsLogic({ experiment: EXPERIMENT })
        metricsLogic.mount()
        logic = experimentResultsNotificationLogic({ experiment: EXPERIMENT })
        logic.mount()
        // Let the metrics logic's afterMount load settle so isRecalculating is a stable false.
        await expectLogic(metricsLogic).toDispatchActions(['setCurrentRecalculation'])
    })

    afterEach(() => {
        jest.useRealTimers()
        logic?.unmount()
        metricsLogic?.unmount()
    })

    it('offers the notification banner once a recalculation has run for the delay', async () => {
        jest.useFakeTimers()
        // Recalculation starts → the offer timer begins.
        metricsLogic.actions.setCurrentRecalculation({ id: 'x', status: 'in_progress' } as any)
        expect(logic.values.showNotificationOffer).toBe(false)

        await jest.advanceTimersByTimeAsync(OFFER_DELAY_MS)
        expect(logic.values.showNotificationOffer).toBe(true)
    })

    it('resets the offer when the recalculation finishes', async () => {
        jest.useFakeTimers()
        metricsLogic.actions.setCurrentRecalculation({ id: 'x', status: 'in_progress' } as any)
        await jest.advanceTimersByTimeAsync(OFFER_DELAY_MS)
        expect(logic.values.showNotificationOffer).toBe(true)

        // Recalculation completes → offer is cleared.
        metricsLogic.actions.setCurrentRecalculation({ id: 'x', status: 'completed' } as any)
        await expectLogic(logic).toDispatchActions(['notifyResultsReady'])
        expect(logic.values.showNotificationOffer).toBe(false)
        expect(logic.values.notifyWhenResultsReady).toBe(false)
    })

    it('dismissNotificationOffer clears both flags', () => {
        logic.actions.setShowNotificationOffer(true)
        logic.actions.setNotifyWhenResultsReady(true)
        logic.actions.dismissNotificationOffer()
        expect(logic.values.showNotificationOffer).toBe(false)
        expect(logic.values.notifyWhenResultsReady).toBe(false)
    })

    it('dismissing the offer disposes the pending timer so it cannot re-show the banner', async () => {
        jest.useFakeTimers()
        metricsLogic.actions.setCurrentRecalculation({ id: 'x', status: 'in_progress' } as any)
        // Dismiss before the offer timer fires.
        logic.actions.dismissNotificationOffer()
        await jest.advanceTimersByTimeAsync(OFFER_DELAY_MS)
        // The timer was disposed, so the offer must stay dismissed.
        expect(logic.values.showNotificationOffer).toBe(false)
    })
})
