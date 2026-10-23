import { expectLogic } from 'kea-test-utils'

import { projectLogic } from 'scenes/projectLogic'

import experimentJson from '~/mocks/fixtures/api/experiments/_experiment_launched.json'
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

    it('does not announce results when the page abandons the run, and drops the subscription', async () => {
        const notificationSpy = jest.fn()
        Object.defineProperty(window, 'Notification', {
            value: Object.assign(notificationSpy, { permission: 'granted' }),
            configurable: true,
        })
        try {
            // The seeded run has a gap, so mount also fires a heal request; let it land before driving the edge.
            await expectLogic(metricsLogic).toFinishAllListeners()
            metricsLogic.actions.setCurrentRecalculation({ id: 'x', status: 'in_progress' } as any)
            logic.actions.setNotifyWhenResultsReady(true)

            metricsLogic.actions.abandonRecalculation('poll_timeout', 'x')

            expect(notificationSpy).not.toHaveBeenCalled()
            expect(logic.values.notifyWhenResultsReady).toBe(false)
            expect(dispatchBeforeUnload()).toBe(false)
        } finally {
            // jsdom has no Notification; leaving the key would make `'Notification' in window` true elsewhere.
            delete (window as any).Notification
        }
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
