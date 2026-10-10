import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { experimentMetricsLogic } from '../experimentMetricsLogic'
import { modalsLogic } from '../modalsLogic'
import { runningTimeLogic } from './runningTimeLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
        error: jest.fn(),
        info: jest.fn(),
    },
}))

const calculateRunningTimeMock = jest.fn()
jest.mock('products/experiments/frontend/generated/api', () => ({
    ...jest.requireActual('products/experiments/frontend/generated/api'),
    experimentsCalculateRunningTimeCreate: (...args: any[]) => calculateRunningTimeMock(...args),
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

const metricResultsWithBaseline = [
    {
        metric_uuid: METRIC_UUID,
        baseline: { key: 'control', number_of_samples: 600, sum: 120, sum_squares: 48 },
        variant_results: [{ key: 'test', number_of_samples: 600, sum: 130, sum_squares: 52 }],
    },
] as any[]

describe('runningTimeLogic', () => {
    let logic: ReturnType<typeof runningTimeLogic.build>
    let experimentLogicInstance: ReturnType<typeof experimentLogic.build>
    let getSpy: jest.SpyInstance | undefined

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/experiments': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team/experiment_holdouts': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team/experiment_saved_metrics': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team/experiments/:id': experiment,
            },
        })
        initKeaTests()
        jest.spyOn(api, 'update')
        api.update.mockClear()
        calculateRunningTimeMock.mockReset()
        ;(lemonToast.error as jest.Mock).mockClear()

        experimentLogicInstance = experimentLogic({ experimentId: EXPERIMENT_ID })
        experimentLogicInstance.mount()
        experimentLogicInstance.actions.setExperiment(experiment)
        experimentLogicInstance.actions.setUnmodifiedExperiment(experiment)
        experimentLogicInstance.actions.setPrimaryMetricsResults(metricResultsWithBaseline)
    })

    afterEach(() => {
        getSpy?.mockRestore()
        getSpy = undefined
        logic?.unmount()
        experimentLogicInstance?.unmount()
    })

    describe('persistRunningTimeEstimate', () => {
        it('auto-persists with the concurrency handshake and absorbs the response version', async () => {
            calculateRunningTimeMock.mockResolvedValue({
                recommended_sample_size: 2000,
                recommended_running_time_days: 20,
            })
            api.update.mockResolvedValue({
                ...experiment,
                version: 4,
                running_time_calculation: { recommended_running_time: 7, recommended_sample_size: 2000 },
            })

            logic = runningTimeLogic({ experiment })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['persistRunningTimeEstimate']).toFinishAllListeners()

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
            calculateRunningTimeMock.mockResolvedValue({
                recommended_sample_size: -2000,
                recommended_running_time_days: -20,
            })

            logic = runningTimeLogic({ experiment })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['persistRunningTimeEstimate']).toFinishAllListeners()

            expect(api.update).not.toHaveBeenCalled()
            expect(logic.values.remainingDays).toBeNull()
        })

        it('drops the estimate silently and resyncs the snapshot when it loses a concurrency race', async () => {
            calculateRunningTimeMock.mockResolvedValue({
                recommended_sample_size: 2000,
                recommended_running_time_days: 20,
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

    describe('save', () => {
        it('keeps the modal open with the edited config when the experiment save fails', async () => {
            // A failed estimate request stops the automatic estimate from saving anything on mount.
            calculateRunningTimeMock.mockRejectedValue(new Error('backend unavailable'))
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
        it('stays true while the automatic estimate is in flight, then settles on success', async () => {
            let resolveCalc: (value: unknown) => void = () => {}
            calculateRunningTimeMock.mockReturnValue(
                new Promise((resolve) => {
                    resolveCalc = resolve
                })
            )
            api.update.mockResolvedValue({ ...experiment, version: 4 })

            logic = runningTimeLogic({ experiment })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadAutomaticCalculation'])
            expect(logic.values.isCalculating).toBe(true)

            resolveCalc({ recommended_sample_size: 2000, recommended_running_time_days: 20 })
            await expectLogic(logic).toDispatchActions(['loadAutomaticCalculationSuccess']).toFinishAllListeners()
            expect(logic.values.isCalculating).toBe(false)
        })

        it('clears calculating when the automatic estimate request fails', async () => {
            // A failed request leaves the result null for good, so calculating must still settle —
            // otherwise the meta bar hangs on "Calculating…" instead of showing a resting state.
            calculateRunningTimeMock.mockRejectedValue(new Error('backend unavailable'))

            logic = runningTimeLogic({ experiment })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadAutomaticCalculationFailure']).toFinishAllListeners()
            expect(logic.values.isCalculating).toBe(false)
        })

        it('follows the recalculation loading state when the recalculation flag is on', async () => {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION], {
                [FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION]: true,
            })
            const metricsLogicInstance = experimentMetricsLogic({ experiment })
            metricsLogicInstance.mount()

            logic = runningTimeLogic({ experiment })
            logic.mount()

            metricsLogicInstance.actions.setRecalculationLoading(true)
            await expectLogic(logic).toMatchValues({ isCalculating: true })

            metricsLogicInstance.actions.setRecalculationLoading(false)
            await expectLogic(logic).toMatchValues({ isCalculating: false })

            metricsLogicInstance.unmount()
        })
    })
})
