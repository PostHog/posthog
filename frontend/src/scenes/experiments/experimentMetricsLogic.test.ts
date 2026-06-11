import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { projectLogic } from 'scenes/projectLogic'

import experimentJson from '~/mocks/fixtures/api/experiments/_experiment_launched_with_funnel_and_trends.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment } from '~/types'

import { experimentMetricsLogic } from './experimentMetricsLogic'

const EXPERIMENT = experimentJson as unknown as Experiment
const PRIMARY_METRIC_UUID = '434cb6ba-7fa6-4ca1-b7a0-8970b2d9a47d'
const SECONDARY_METRIC_UUID = 'cbdd02f8-4a27-4017-a8d8-5f989b304ada'

const primaryResult = { some: 'primary-result' }
const secondaryResult = { some: 'secondary-result' }

const completedRecalculation = {
    id: 'recalc-1',
    experiment_id: EXPERIMENT.id,
    status: 'completed',
    total_metrics: 2,
    completed_metrics: 2,
    failed_metrics: 0,
    metric_errors: {},
    trigger: 'manual',
    created_at: '2026-06-10T00:00:00Z',
    started_at: '2026-06-10T00:00:00Z',
    completed_at: '2026-06-10T00:00:10Z',
    is_existing: false,
    results: [
        { metric_uuid: PRIMARY_METRIC_UUID, status: 'completed', result: primaryResult, error_message: null },
        { metric_uuid: SECONDARY_METRIC_UUID, status: 'completed', result: secondaryResult, error_message: null },
    ],
}

describe('experimentMetricsLogic', () => {
    let logic: ReturnType<typeof experimentMetricsLogic.build>

    beforeEach(async () => {
        // Default handler so every afterMount-driven load has a mock; tests override per-case.
        useMocks({
            get: {
                '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [404, {}],
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

        it('leaves state untouched and shows no error on 404 (no completed recalc yet)', async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [
                        404,
                        { detail: 'No completed recalculation found' },
                    ],
                },
            })
            mountLogic()

            // afterMount fires loadLatestRecalculation; the 404 must leave everything at its default.
            await expectLogic(logic).toDispatchActions(['loadLatestRecalculation', 'setRecalculationLoading'])

            expect(logic.values.currentRecalculation).toBeNull()
            expect(logic.values.primaryMetricsResults).toEqual([])
            expect(logic.values.secondaryMetricsResults).toEqual([])
            expect(logic.values.recalculationLoading).toBe(false)
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
    })
})
