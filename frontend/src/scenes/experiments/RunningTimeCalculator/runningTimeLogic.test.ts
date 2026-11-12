import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { experimentMetricsLogic } from '../experimentMetricsLogic'
import { modalsLogic } from '../modalsLogic'
import { roundUpDetectableEffect } from './calculations'
import { runningTimeLogic } from './runningTimeLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
        error: jest.fn(),
        info: jest.fn(),
    },
}))

const runningTimeTargetMock = jest.fn()
jest.mock('products/experiments/frontend/generated/api', () => ({
    ...jest.requireActual('products/experiments/frontend/generated/api'),
    experimentsRunningTimeTargetRetrieve: (...args: any[]) => runningTimeTargetMock(...args),
}))

const EXPERIMENT_ID = 99
const METRIC_UUID = 'metric-1'

// A launched experiment ten days in, so the automatic estimate has a live baseline to work from.
const TEN_DAYS_AGO = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString()
const experiment = {
    id: EXPERIMENT_ID,
    name: 'Auto-save race',
    feature_flag_key: 'autosave-race',
    start_date: TEN_DAYS_AGO,
    end_date: null,
    metrics: [
        {
            kind: 'ExperimentMetric',
            uuid: METRIC_UUID,
            metric_type: 'mean',
            source: { kind: 'EventsNode', event: '$pageview' },
        },
    ],
    metrics_secondary: [],
    saved_metrics: [],
    primary_metrics_ordered_uuids: [METRIC_UUID],
    secondary_metrics_ordered_uuids: [],
    parameters: {},
    running_time_calculation: {},
    version: 3,
} as unknown as Experiment

const metricResultWithBaseline = {
    metric_uuid: METRIC_UUID,
    baseline: { key: 'control', number_of_samples: 600, sum: 120, sum_squares: 48 },
    variant_results: [{ key: 'test', number_of_samples: 600, sum: 130, sum_squares: 52 }],
}

// The backend's projection for the result above: 1,200 exposures over ten days.
const PROJECTION = {
    days_since_launch: 10,
    exposures_per_day: 120,
    detectable_effect_now: 38.7,
    upcoming_checkpoints: [{ weeks_since_launch: 2, detectable_effect: 32.7 }],
    reachable_effect: 25.4,
}

// The latest completed run covers the one primary metric, so the metrics logic applies the baseline on mount.
const latestRecalculation = {
    id: 'recalc-1',
    experiment_id: EXPERIMENT_ID,
    status: 'completed',
    trigger: 'manual',
    total_metrics: 1,
    completed_metrics: 1,
    failed_metrics: 0,
    metric_errors: {},
    created_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    query_to: new Date().toISOString(),
    result_source: 'recalculation',
    results: [{ metric_uuid: METRIC_UUID, status: 'completed', result: metricResultWithBaseline, error_message: null }],
}

describe('runningTimeLogic', () => {
    let logic: ReturnType<typeof runningTimeLogic.build>
    let experimentLogicInstance: ReturnType<typeof experimentLogic.build>
    let metricsLogicInstance: ReturnType<typeof experimentMetricsLogic.build>
    let getSpy: jest.SpyInstance | undefined

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/experiments': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team/experiment_holdouts': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team/experiment_saved_metrics': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team/experiments/:id': experiment,
                '/api/projects/:team/experiments/:id/metrics_recalculation/latest/': latestRecalculation,
            },
        })
        initKeaTests()
        jest.spyOn(api, 'update')
        api.update.mockClear()
        runningTimeTargetMock.mockReset()
        ;(lemonToast.error as jest.Mock).mockClear()

        experimentLogicInstance = experimentLogic({ experimentId: EXPERIMENT_ID })
        experimentLogicInstance.mount()
        experimentLogicInstance.actions.setExperiment(experiment)
        experimentLogicInstance.actions.setUnmodifiedExperiment(experiment)
        metricsLogicInstance = experimentMetricsLogic({ experiment })
        metricsLogicInstance.mount()
        await expectLogic(metricsLogicInstance).toDispatchActions(['setCurrentRecalculation'])
    })

    afterEach(() => {
        getSpy?.mockRestore()
        getSpy = undefined
        logic?.unmount()
        metricsLogicInstance?.unmount()
        experimentLogicInstance?.unmount()
    })

    describe('persistRunningTimeEstimate', () => {
        it('auto-persists with the concurrency handshake and absorbs the response version', async () => {
            runningTimeTargetMock.mockResolvedValue({
                recommended_sample_size: 2000,
                minimum_detectable_effect: 30,
                outlook: PROJECTION,
            })
            api.update.mockResolvedValue({
                ...experiment,
                version: 4,
                running_time_calculation: { recommended_running_time: 7, recommended_sample_size: 2000 },
            })

            logic = runningTimeLogic({ experiment })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['persistRunningTimeEstimate']).toFinishAllListeners()

            expect(runningTimeTargetMock).toHaveBeenCalledWith(expect.any(String), EXPERIMENT_ID, {
                mode: 'automatic',
            })
            // Without the version handshake this write bumps the server version invisibly,
            // making every later scalar save from any open tab a guaranteed 409.
            expect(api.update).toHaveBeenCalledWith(
                expect.stringContaining(`/experiments/${EXPERIMENT_ID}`),
                expect.objectContaining({
                    version: 3,
                    original_experiment: expect.objectContaining({ metrics: experiment.metrics }),
                    running_time_calculation: expect.objectContaining({ recommended_sample_size: 2000 }),
                })
            )
            expect(experimentLogicInstance.values.unmodifiedExperiment?.version).toEqual(4)
            expect(lemonToast.error).not.toHaveBeenCalled()
        })

        it('never persists a non-positive estimate', async () => {
            // A bad baseline can make the backend return a negative sample size. It must not reach the record.
            runningTimeTargetMock.mockResolvedValue({
                recommended_sample_size: -2000,
                minimum_detectable_effect: 30,
            })

            logic = runningTimeLogic({ experiment })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['persistRunningTimeEstimate']).toFinishAllListeners()

            expect(api.update).not.toHaveBeenCalled()
            expect(logic.values.remainingDays).toBeNull()
        })

        it('drops the estimate silently and resyncs the snapshot when it loses a concurrency race', async () => {
            runningTimeTargetMock.mockResolvedValue({
                recommended_sample_size: 2000,
                minimum_detectable_effect: 30,
                outlook: PROJECTION,
            })
            api.update.mockRejectedValue({
                status: 409,
                data: { detail: 'This experiment changed since you loaded it.', current_version: 9 },
            })
            getSpy = jest.spyOn(api, 'get').mockResolvedValue({
                ...experiment,
                version: 9,
                running_time_calculation: { recommended_running_time: 11, recommended_sample_size: 2400 },
            })

            logic = runningTimeLogic({ experiment })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['persistRunningTimeEstimate']).toFinishAllListeners()

            // A machine-written estimate losing a race is not a user problem: no error toast,
            // just resync so the tab stops being stale and the estimate recomputes from fresh state.
            expect(lemonToast.error).not.toHaveBeenCalled()
            expect(experimentLogicInstance.values.unmodifiedExperiment?.version).toEqual(9)
        })
    })

    describe('automatic target', () => {
        it('rescales the target for an edited effect without asking the backend', async () => {
            runningTimeTargetMock.mockResolvedValue({ recommended_sample_size: 2000, minimum_detectable_effect: 30 })
            api.update.mockResolvedValue({ ...experiment, version: 4 })

            logic = runningTimeLogic({ experiment })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadAutomaticTargetSuccess']).toFinishAllListeners()
            runningTimeTargetMock.mockClear()

            logic.actions.setConfig({ mde: 15 })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.targetSampleSize).toEqual(8000)
            expect(runningTimeTargetMock).not.toHaveBeenCalled()
        })

        it('counts the exposures the backend sizes the target over', async () => {
            // The results hold 1,200 exposures. The backend counts 1,100, because one variant is at 0%.
            runningTimeTargetMock.mockResolvedValue({
                recommended_sample_size: 2000,
                minimum_detectable_effect: 30,
                current_sample_size: 1100,
            })
            api.update.mockResolvedValue({ ...experiment, version: 4 })

            logic = runningTimeLogic({ experiment })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadAutomaticTargetSuccess']).toFinishAllListeners()

            expect(logic.values.currentExposures).toEqual(1100)
        })

        it('counts the days left on the projection, also before 100 exposures and with results from before today', async () => {
            // 90 exposures in results that end on day 9 make 10 a day, so the 180 of the target arrive on day 18.
            runningTimeTargetMock.mockResolvedValue({
                recommended_sample_size: 180,
                minimum_detectable_effect: 30,
                current_sample_size: 90,
                outlook: { ...PROJECTION, days_since_launch: 10, exposures_per_day: 10 },
            })
            api.update.mockResolvedValue({ ...experiment, version: 4 })

            logic = runningTimeLogic({ experiment })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadAutomaticTargetSuccess']).toFinishAllListeners()

            expect(logic.values.remainingDays).toEqual(8)
        })

        it('keeps the same rows while the user takes a row with "Use" and moves the slider', async () => {
            // At 120 exposures a day, the 1,996 that 30% needs arrive after week 2, which can detect 32.7%.
            runningTimeTargetMock.mockResolvedValue({
                recommended_sample_size: 1996,
                minimum_detectable_effect: 30,
                current_sample_size: 1200,
                outlook: PROJECTION,
            })
            api.update.mockResolvedValue({ ...experiment, version: 4 })
            logic = runningTimeLogic({ experiment })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadAutomaticTargetSuccess']).toFinishAllListeners()
            const rows = (): [number, boolean][] | undefined =>
                logic.values.outlook?.checkpoints.map(({ detectableEffect, isTarget }) => [detectableEffect, isTarget])

            expect(rows()).toEqual([
                [38.7, false],
                [32.7, false],
                [30, true],
            ])

            logic.actions.selectCheckpoint('week-2', roundUpDetectableEffect(32.7))

            expect(rows()).toEqual([
                [38.7, false],
                [32.7, true],
                [30, false],
            ])
            expect(logic.values.remainingDays).toEqual(4)
            expect(logic.values.config.mde).toEqual(32.7)

            logic.actions.setConfig({ mde: 36 })

            expect(rows()).toEqual([
                [38.7, false],
                [36, true],
                [32.7, false],
            ])
        })

        it('asks again when the metric sums change without new exposures', async () => {
            runningTimeTargetMock.mockResolvedValue({ recommended_sample_size: 2000, minimum_detectable_effect: 30 })
            api.update.mockResolvedValue({ ...experiment, version: 4 })

            logic = runningTimeLogic({ experiment })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadAutomaticTargetSuccess']).toFinishAllListeners()

            metricsLogicInstance.actions.setPrimaryMetricsResults([
                {
                    ...metricResultWithBaseline,
                    baseline: { ...metricResultWithBaseline.baseline, sum: 150, sum_squares: 90 },
                } as any,
            ])
            await expectLogic(logic).toDispatchActions(['loadAutomaticTarget']).toFinishAllListeners()

            expect(runningTimeTargetMock).toHaveBeenCalledTimes(2)
        })
    })

    describe('save', () => {
        it('persists the estimate the backend sizes for the saved effect', async () => {
            runningTimeTargetMock.mockResolvedValueOnce({
                recommended_sample_size: 2000,
                minimum_detectable_effect: 30,
                outlook: PROJECTION,
            })
            api.update.mockImplementation(async (_url: string, payload: unknown) => ({
                ...experiment,
                ...(payload as Partial<Experiment>),
                version: 4,
            }))

            const captureSpy = jest.spyOn(posthog, 'capture')
            logic = runningTimeLogic({ experiment })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadAutomaticTargetSuccess']).toFinishAllListeners()
            const savedMde = logic.values.config.mde
            modalsLogic.actions.openRunningTimeConfigModal()
            logic.actions.setConfig({ mde: 15 })
            runningTimeTargetMock.mockResolvedValueOnce({
                recommended_sample_size: 8000,
                minimum_detectable_effect: 15,
                outlook: PROJECTION,
            })
            api.update.mockClear()

            await expectLogic(logic, () => logic.actions.save())
                .toDispatchActions(['loadAutomaticTargetSuccess'])
                .toFinishAllListeners()

            expect(api.update).toHaveBeenLastCalledWith(
                expect.stringContaining(`/experiments/${EXPERIMENT_ID}`),
                expect.objectContaining({
                    running_time_calculation: expect.objectContaining({
                        minimum_detectable_effect: 15,
                        recommended_sample_size: 8000,
                    }),
                })
            )
            expect(captureSpy).toHaveBeenCalledWith(
                'experiment running time settings saved',
                expect.objectContaining({ minimum_detectable_effect: 15, previous_minimum_detectable_effect: savedMde })
            )
            captureSpy.mockRestore()
        })

        it('keeps the modal open with the edited config when the experiment save fails', async () => {
            // A failed estimate request stops the automatic estimate from saving anything on mount.
            runningTimeTargetMock.mockRejectedValue(new Error('backend unavailable'))
            api.update.mockRejectedValueOnce(new Error('network down'))

            logic = runningTimeLogic({ experiment })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            modalsLogic.actions.openRunningTimeConfigModal()
            logic.actions.setConfig({ mde: 7 })

            await expectLogic(logic, () => logic.actions.save()).toFinishAllListeners()

            expect(api.update).toHaveBeenCalledTimes(1)
            expect(modalsLogic.values.isRunningTimeConfigModalOpen).toBe(true)
            expect(logic.values.configOverrides).toEqual({ mde: 7 })
            // The experiment save reports the failure itself, so the modal adds no second toast.
            expect(lemonToast.error).toHaveBeenCalledTimes(1)
        })
    })

    describe('isCalculating', () => {
        it.each([
            ['an automatic experiment', {}, null],
            [
                'a manual experiment switched to automatic',
                { exposure_estimate_config: { conversionRateInputType: 'manual' } },
                { mode: 'automatic' as const },
            ],
        ])('stays true while the estimate of %s is in flight, then settles', async (_name, saved, edit) => {
            let resolveCalc: (value: unknown) => void = () => {}
            runningTimeTargetMock.mockReturnValue(
                new Promise((resolve) => {
                    resolveCalc = resolve
                })
            )
            api.update.mockResolvedValue({ ...experiment, version: 4 })
            experimentLogicInstance.actions.setExperiment({
                ...experiment,
                running_time_calculation: saved as Experiment['running_time_calculation'],
            })

            logic = runningTimeLogic({ experiment })
            logic.mount()
            if (edit) {
                logic.actions.setConfig(edit)
            }

            await expectLogic(logic).toDispatchActions(['loadAutomaticTarget'])
            expect(logic.values.isCalculating).toBe(true)

            resolveCalc({ recommended_sample_size: 2000, minimum_detectable_effect: 30 })
            await expectLogic(logic).toDispatchActions(['loadAutomaticTargetSuccess']).toFinishAllListeners()
            expect(logic.values.isCalculating).toBe(false)
        })

        it('clears calculating when the automatic estimate request fails', async () => {
            // A failed request leaves the result null for good, so calculating must still settle —
            // otherwise the meta bar hangs on "Calculating…" instead of showing a resting state.
            runningTimeTargetMock.mockRejectedValue(new Error('backend unavailable'))

            logic = runningTimeLogic({ experiment })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadAutomaticTargetFailure']).toFinishAllListeners()
            expect(logic.values.isCalculating).toBe(false)
        })

        it('follows the recalculation loading state', async () => {
            runningTimeTargetMock.mockResolvedValue({
                recommended_sample_size: 2000,
                minimum_detectable_effect: 30,
                outlook: PROJECTION,
            })

            logic = runningTimeLogic({ experiment })
            logic.mount()
            // The baseline fires the automatic estimate on mount; let it settle so only the recalculation state moves.
            await expectLogic(logic).toDispatchActions(['loadAutomaticTargetSuccess']).toFinishAllListeners()
            expect(logic.values.isCalculating).toBe(false)

            metricsLogicInstance.actions.setRecalculationLoading(true)
            await expectLogic(logic).toMatchValues({ isCalculating: true })

            metricsLogicInstance.actions.setRecalculationLoading(false)
            await expectLogic(logic).toMatchValues({ isCalculating: false })
        })
    })
})
