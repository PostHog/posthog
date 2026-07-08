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

const dispatchBeforeUnload = (): boolean => {
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    return event.defaultPrevented
}

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
        logic?.unmount()
        metricsLogic?.unmount()
    })

    it('fires notifyResultsReady and resets the subscription when the recalculation finishes', async () => {
        metricsLogic.actions.setCurrentRecalculation({ id: 'x', status: 'in_progress' } as any)
        logic.actions.setNotifyWhenResultsReady(true)

        metricsLogic.actions.setCurrentRecalculation({ id: 'x', status: 'completed' } as any)
        await expectLogic(logic).toDispatchActions(['notifyResultsReady'])
        expect(logic.values.notifyWhenResultsReady).toBe(false)
    })

    it('warns before unload while subscribed and stops once results land', async () => {
        metricsLogic.actions.setCurrentRecalculation({ id: 'x', status: 'in_progress' } as any)
        expect(dispatchBeforeUnload()).toBe(false)

        logic.actions.setNotifyWhenResultsReady(true)
        expect(dispatchBeforeUnload()).toBe(true)

        metricsLogic.actions.setCurrentRecalculation({ id: 'x', status: 'completed' } as any)
        await expectLogic(logic).toDispatchActions(['notifyResultsReady'])
        expect(dispatchBeforeUnload()).toBe(false)
    })
})
