import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
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
})
