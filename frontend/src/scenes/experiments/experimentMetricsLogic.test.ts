import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { projectLogic } from 'scenes/projectLogic'

import experimentJson from '~/mocks/fixtures/api/experiments/_experiment_launched_with_funnel_and_trends.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment } from '~/types'

import { experimentMetricsLogic } from './experimentMetricsLogic'

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    lemonToast: { error: jest.fn(), success: jest.fn(), info: jest.fn() },
}))

// Mirrors the private poll interval in experimentMetricsLogic.
const POLL_INTERVAL_MS = 2000
// Mirrors the private MAX_POLL_RETRIES in experimentMetricsLogic.
const MAX_POLL_RETRIES = 5

const EXPERIMENT = experimentJson as unknown as Experiment
const PRIMARY_METRIC_UUID = '434cb6ba-7fa6-4ca1-b7a0-8970b2d9a47d'
const SECONDARY_METRIC_UUID = 'cbdd02f8-4a27-4017-a8d8-5f989b304ada'

const primaryResult = { some: 'primary-result' }
const secondaryResult = { some: 'secondary-result' }

const baseRecalculation = {
    experiment_id: EXPERIMENT.id,
    total_metrics: 2,
    completed_metrics: 0,
    failed_metrics: 0,
    metric_errors: {},
    trigger: 'manual',
    created_at: '2026-06-10T00:00:00Z',
    started_at: null,
    completed_at: null,
    is_existing: false,
    results: [],
}

const completedRecalculation = {
    ...baseRecalculation,
    id: 'recalc-1',
    status: 'completed',
    completed_metrics: 2,
    started_at: new Date().toISOString(),
    // Fresh by default (within the 24h window) so tests using this fixture don't auto-trigger.
    completed_at: new Date().toISOString(),
    results: [
        { metric_uuid: PRIMARY_METRIC_UUID, status: 'completed', result: primaryResult, error_message: null },
        { metric_uuid: SECONDARY_METRIC_UUID, status: 'completed', result: secondaryResult, error_message: null },
    ],
}

// completed_at far in the past → older than the 24h staleness threshold.
const staleCompletedRecalculation = {
    ...completedRecalculation,
    completed_at: '2020-01-01T00:00:00Z',
}
const freshCompletedRecalculation = completedRecalculation

const pendingRecalculation = { ...baseRecalculation, id: 'recalc-2', status: 'pending' }
const inProgressRecalculation = { ...baseRecalculation, id: 'recalc-2', status: 'in_progress' }
const completedRecalculation2 = { ...completedRecalculation, id: 'recalc-2' }

// Run finished but the primary metric failed and the secondary succeeded — a partial failure.
const partialFailureRecalculation = {
    ...baseRecalculation,
    id: 'recalc-2',
    status: 'failed',
    total_metrics: 2,
    completed_metrics: 1,
    failed_metrics: 1,
    completed_at: new Date().toISOString(),
    metric_errors: { [PRIMARY_METRIC_UUID]: { step: 'calculation', message: 'boom' } },
    results: [
        { metric_uuid: PRIMARY_METRIC_UUID, status: 'failed', result: null, error_message: 'boom' },
        { metric_uuid: SECONDARY_METRIC_UUID, status: 'completed', result: secondaryResult, error_message: null },
    ],
}

describe('experimentMetricsLogic', () => {
    let logic: ReturnType<typeof experimentMetricsLogic.build>

    beforeEach(async () => {
        // Default handlers so every afterMount-driven load/trigger has a mock; tests override per-case.
        useMocks({
            get: {
                '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [404, {}],
            },
            post: {
                '/api/projects/:team_id/experiments/:id/metrics_recalculation/': () => [201, pendingRecalculation],
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION], {
            [FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION]: true,
        })
        // Wait for the bootstrap to populate currentProjectId — the loader guards on it.
        await expectLogic(projectLogic).toMatchValues({ currentProjectId: expect.any(Number) })
    })

    afterEach(async () => {
        // Let the afterMount load settle before unmount so its promise can't bleed into the next test.
        await new Promise((resolve) => setTimeout(resolve, 0))
        logic?.unmount()
    })

    const mountLogic = (): void => {
        logic = experimentMetricsLogic({ experiment: EXPERIMENT })
        logic.mount()
    }

    it('is keyed by the experiment id', () => {
        mountLogic()
        expect(logic.key).toEqual(EXPERIMENT.id)
    })

    describe('loadLatestRecalculation', () => {
        it('loads the latest completed recalculation and maps results by metric position', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [
                        200,
                        completedRecalculation,
                    ],
                },
            })
            mountLogic()

            // afterMount fires loadLatestRecalculation on its own — no manual dispatch needed.
            await expectLogic(logic).toDispatchActions([
                'setCurrentRecalculation',
                'setPrimaryMetricsResults',
                'setSecondaryMetricsResults',
            ])

            expect(logic.values.currentRecalculation).toEqual(
                expect.objectContaining({ id: 'recalc-1', status: 'completed' })
            )
            // saved_metrics in the fixture have no query uuid, so they map to undefined positions —
            // the inline metric result lands first.
            expect(logic.values.primaryMetricsResults[0]).toEqual(primaryResult)
            expect(logic.values.secondaryMetricsResults[0]).toEqual(secondaryResult)
            expect(logic.values.recalculationLoading).toBe(false)
        })

        it('shows no error toast on 404 (a fresh recalc is triggered instead)', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [
                        404,
                        { detail: 'No completed recalculation found' },
                    ],
                },
                post: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/': () => [201, pendingRecalculation],
                },
            })
            mountLogic()

            // 404 routes to triggerRecalculation, not an error; results stay empty until it completes.
            await expectLogic(logic).toDispatchActions(['loadLatestRecalculation', 'triggerRecalculation'])

            expect(lemonToast.error).not.toHaveBeenCalled()
            expect(logic.values.primaryMetricsResults).toEqual([])
            expect(logic.values.secondaryMetricsResults).toEqual([])
        })

        it('toggles recalculationLoading true while in flight then false when done', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [
                        200,
                        completedRecalculation,
                    ],
                },
            })
            mountLogic()

            // afterMount fires the load synchronously enough that loading flips true immediately.
            expect(logic.values.recalculationLoading).toBe(true)

            await expectLogic(logic).toDispatchActions(['setCurrentRecalculation'])
            expect(logic.values.recalculationLoading).toBe(false)
        })

        it('triggers a new recalculation when latest returns 404', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [404, {}],
                },
                post: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/': () => [201, pendingRecalculation],
                },
            })
            mountLogic()

            // afterMount → loadLatestRecalculation → 404 → triggerRecalculation → create → store pending
            await expectLogic(logic).toDispatchActions(['triggerRecalculation', 'setCurrentRecalculation'])
            expect(logic.values.currentRecalculation).toEqual(
                expect.objectContaining({ id: 'recalc-2', status: 'pending' })
            )
        })

        it('auto-triggers a fresh recalculation when the latest completed run is stale (>24h)', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [
                        200,
                        staleCompletedRecalculation,
                    ],
                },
                post: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/': () => [201, pendingRecalculation],
                },
            })
            mountLogic()

            // Stale results still load, but a fresh run is kicked off in the background.
            await expectLogic(logic).toDispatchActions(['setCurrentRecalculation', 'triggerRecalculation'])
            expect(logic.values.primaryMetricsResults[0]).toEqual(primaryResult)
        })

        it('does not auto-trigger when the latest completed run is fresh', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [
                        200,
                        freshCompletedRecalculation,
                    ],
                },
            })
            mountLogic()

            await expectLogic(logic)
                .toDispatchActions(['setCurrentRecalculation'])
                .toNotHaveDispatchedActions(['triggerRecalculation'])
        })

        it('starts polling after triggering a non-terminal recalculation', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [404, {}],
                },
                post: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/': () => [
                        201,
                        inProgressRecalculation,
                    ],
                },
            })
            mountLogic()

            await expectLogic(logic).toDispatchActions(['triggerRecalculation', 'pollRecalculation'])
        })

        it('does not poll when the triggered recalculation is already terminal', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [404, {}],
                },
                post: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/': () => [
                        201,
                        completedRecalculation2,
                    ],
                },
            })
            mountLogic()

            await expectLogic(logic)
                .toDispatchActions(['triggerRecalculation', 'setCurrentRecalculation', 'setPrimaryMetricsResults'])
                .toNotHaveDispatchedActions(['pollRecalculation'])

            // A terminal create response must still load its results (not just store the recalc).
            expect(logic.values.primaryMetricsResults[0]).toEqual(primaryResult)
        })
    })

    describe('loading + progress selectors', () => {
        it('exposes progress and isRecalculating while a run is in progress', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [
                        200,
                        { ...inProgressRecalculation, total_metrics: 5, completed_metrics: 2 },
                    ],
                },
            })
            mountLogic()

            await expectLogic(logic).toDispatchActions(['setCurrentRecalculation'])

            expect(logic.values.recalculationProgress).toEqual({ completed: 2, total: 5 })
            // in_progress is non-terminal → still recalculating
            expect(logic.values.isRecalculating).toBe(true)
        })

        it('is not recalculating once the run is completed', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [
                        200,
                        completedRecalculation,
                    ],
                },
            })
            mountLogic()

            await expectLogic(logic).toDispatchActions(['setCurrentRecalculation'])

            expect(logic.values.recalculationProgress).toEqual({ completed: 2, total: 2 })
            expect(logic.values.isRecalculating).toBe(false)
            // lastRefresh comes from the completed run's completion time.
            expect(logic.values.lastRefresh).toEqual(completedRecalculation.completed_at)
        })

        it('defaults progress to zeroes and lastRefresh to null when there is no recalculation', () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [404, {}],
                },
            })
            mountLogic()

            expect(logic.values.recalculationProgress).toEqual({ completed: 0, total: 0 })
            expect(logic.values.lastRefresh).toBeNull()
        })
    })

    describe('pollRecalculation', () => {
        afterEach(() => {
            jest.useRealTimers()
        })

        it('polls until completed, then loads results and stops', async () => {
            // First retrieve still in progress, second completed.
            let call = 0
            useMocks({
                get: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [404, {}],
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/:recalc_id/': () => {
                        call += 1
                        return [200, call === 1 ? inProgressRecalculation : completedRecalculation2]
                    },
                },
                post: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/': () => [
                        201,
                        inProgressRecalculation,
                    ],
                },
            })
            // Fake timers BEFORE mount so the breakpoint's very first setTimeout is fake too.
            jest.useFakeTimers()
            mountLogic()

            // Flush the afterMount → 404 → trigger → poll(create) promise chain, then drive the loop.
            await jest.advanceTimersByTimeAsync(0)
            for (let i = 0; i < 4; i++) {
                await jest.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
            }

            expect(logic.values.currentRecalculation).toEqual(expect.objectContaining({ status: 'completed' }))
            expect(logic.values.primaryMetricsResults[0]).toEqual(primaryResult)
        })

        it('on partial failure: loads successes, sets per-metric errors, and shows a tailored toast', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [404, {}],
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/:recalc_id/': () => [
                        200,
                        partialFailureRecalculation,
                    ],
                },
                post: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/': () => [
                        201,
                        inProgressRecalculation,
                    ],
                },
            })
            jest.useFakeTimers()
            mountLogic()

            await jest.advanceTimersByTimeAsync(0)
            for (let i = 0; i < 2; i++) {
                await jest.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
            }

            // Tailored toast counts the failures against the total.
            expect(lemonToast.error).toHaveBeenCalledWith('1 of 2 metrics failed to load')
            expect(logic.values.currentRecalculation).toEqual(expect.objectContaining({ status: 'failed' }))
            // The successful secondary metric still loads its result.
            expect(logic.values.secondaryMetricsResults[0]).toEqual(secondaryResult)
            // The failed primary metric gets an error with the failure message for its in-row box.
            expect(logic.values.primaryMetricsResultsErrors[0]).toEqual({ detail: 'boom' })
        })

        it('gives up after MAX_POLL_RETRIES consecutive retrieve failures', async () => {
            let retrieveCalls = 0
            useMocks({
                get: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [404, {}],
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/:recalc_id/': () => {
                        retrieveCalls += 1
                        return [500, {}]
                    },
                },
                post: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/': () => [
                        201,
                        inProgressRecalculation,
                    ],
                },
            })
            jest.useFakeTimers()
            mountLogic()

            // Flush afterMount → 404 → trigger → poll(create), then drive enough ticks to exhaust retries.
            await jest.advanceTimersByTimeAsync(0)
            for (let i = 0; i < MAX_POLL_RETRIES + 2; i++) {
                await jest.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
            }

            // Stops retrieving once the cap is hit and surfaces an error; never loops forever.
            expect(retrieveCalls).toBe(MAX_POLL_RETRIES)
            expect(lemonToast.error).toHaveBeenCalledWith(
                'Failed to load recalculation results. Please reload to try again.'
            )
        })
    })

    describe('tab focus does not clobber a loaded run', () => {
        it('does not reload latest on focus once a run is already loaded', async () => {
            const latestMock = jest.fn(() => [200, completedRecalculation])
            useMocks({
                get: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': latestMock,
                },
            })
            mountLogic()

            // Mount fires one load.
            await expectLogic(logic).toDispatchActions(['setCurrentRecalculation'])
            expect(latestMock).toHaveBeenCalledTimes(1)

            // Simulate tab focus — the handler must NOT reload, because a run is already loaded.
            document.dispatchEvent(new Event('visibilitychange'))
            await expectLogic(logic).toNotHaveDispatchedActions(['loadLatestRecalculation'])
            expect(latestMock).toHaveBeenCalledTimes(1)
        })
    })

    describe('feature flag disabled (legacy path)', () => {
        it('is a no-op on mount: no API calls, no recalc state', async () => {
            // Flip the flag off — the legacy flow owns metrics; this logic must do nothing.
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION], {
                [FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION]: false,
            })
            const latestMock = jest.fn(() => [200, completedRecalculation])
            const createMock = jest.fn(() => [201, pendingRecalculation])
            useMocks({
                get: { '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': latestMock },
                post: { '/api/projects/:team_id/experiments/:id/metrics_recalculation/': createMock },
            })
            mountLogic()

            // afterMount still dispatches loadLatestRecalculation, but the flag guard bails immediately.
            await expectLogic(logic)
                .toDispatchActions(['loadLatestRecalculation'])
                .toNotHaveDispatchedActions(['setCurrentRecalculation', 'triggerRecalculation', 'pollRecalculation'])

            // No recalculation endpoints were ever called, and state stays at its defaults.
            expect(latestMock).not.toHaveBeenCalled()
            expect(createMock).not.toHaveBeenCalled()
            expect(logic.values.currentRecalculation).toBeNull()
            expect(logic.values.recalculationLoading).toBe(false)
            expect(logic.values.isRecalculating).toBe(false)
        })

        it('triggerRecalculation and loadLatestRecalculation no-op when the flag is off', async () => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION], {
                [FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION]: false,
            })
            const createMock = jest.fn(() => [201, pendingRecalculation])
            useMocks({
                get: { '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [404, {}] },
                post: { '/api/projects/:team_id/experiments/:id/metrics_recalculation/': createMock },
            })
            mountLogic()

            // Even an explicit trigger does nothing while the flag is off.
            await expectLogic(logic, () => {
                logic.actions.triggerRecalculation()
            }).toNotHaveDispatchedActions(['pollRecalculation', 'setCurrentRecalculation'])
            expect(createMock).not.toHaveBeenCalled()
        })
    })
})
