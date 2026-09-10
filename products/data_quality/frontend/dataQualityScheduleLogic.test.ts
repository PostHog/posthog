import { ApiError } from 'lib/api'

import { silenceKeaLoadersErrors, resumeKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { dataQualityScheduleLogic } from './dataQualityScheduleLogic'
import {
    dataCatalogMetricsChecksScheduleRetrieve,
    dataCatalogMetricsChecksSchedulePartialUpdate,
} from './generated/api'

jest.mock('./generated/api', () => ({
    dataCatalogMetricsChecksScheduleRetrieve: jest.fn(),
    dataCatalogMetricsChecksSchedulePartialUpdate: jest.fn(),
}))

const SCHEDULE = {
    id: 'schedule-1',
    enabled: true,
    interval: '24hour',
    next_run_at: '2026-09-05T00:00:00Z',
    last_run_at: null,
    last_suite_run: null,
}

describe('dataQualityScheduleLogic', () => {
    let logic: ReturnType<typeof dataQualityScheduleLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        silenceKeaLoadersErrors()
        ;(dataCatalogMetricsChecksScheduleRetrieve as jest.Mock).mockResolvedValue(SCHEDULE)
        logic = dataQualityScheduleLogic({ metricId: 'metric-1' })
    })

    afterEach(() => {
        logic.unmount()
        resumeKeaLoadersErrors()
    })

    it('loads the metric schedule and saves only the changed setting', async () => {
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.schedule).toEqual(SCHEDULE)
        ;(dataCatalogMetricsChecksSchedulePartialUpdate as jest.Mock).mockResolvedValue({
            ...SCHEDULE,
            interval: '6hour',
        })
        logic.actions.updateSchedule({ interval: '6hour' })
        await expectLogic(logic).toFinishAllListeners()
        expect(dataCatalogMetricsChecksSchedulePartialUpdate).toHaveBeenCalledWith('997', 'metric-1', {
            interval: '6hour',
        })
        expect(logic.values.schedule).toMatchObject({ interval: '6hour', enabled: true })
    })

    it('keeps the persisted schedule visible after a rejected edit and can retry', async () => {
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        ;(dataCatalogMetricsChecksSchedulePartialUpdate as jest.Mock).mockRejectedValue(new Error('Could not save'))
        logic.actions.updateSchedule({ enabled: false })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.schedule?.enabled).toBe(true)
        expect(logic.values.scheduleError).toBeTruthy()
        expect(logic.values.scheduleLoading).toBe(false)
        ;(dataCatalogMetricsChecksSchedulePartialUpdate as jest.Mock).mockResolvedValue({ ...SCHEDULE, enabled: false })
        logic.actions.updateSchedule({ enabled: false })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.schedule?.enabled).toBe(false)
        expect(logic.values.scheduleError).toBeNull()
    })
    it('refetches persisted state when an edit response is lost', async () => {
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        ;(dataCatalogMetricsChecksSchedulePartialUpdate as jest.Mock).mockRejectedValue(new Error('Connection lost'))
        ;(dataCatalogMetricsChecksScheduleRetrieve as jest.Mock).mockResolvedValue({
            ...SCHEDULE,
            enabled: false,
            next_run_at: null,
        })
        logic.actions.updateSchedule({ enabled: false })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.schedule?.enabled).toBe(false)
        expect(logic.values.scheduleError?.uncertain).toBe(true)
        expect(logic.values.scheduleLoading).toBe(false)
    })

    it('reports a denied edit without refetching the schedule', async () => {
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        ;(dataCatalogMetricsChecksScheduleRetrieve as jest.Mock).mockClear()
        ;(dataCatalogMetricsChecksSchedulePartialUpdate as jest.Mock).mockRejectedValue(
            new ApiError('Forbidden', 403, undefined, {
                detail: 'You do not have permission to perform this action.',
            })
        )
        logic.actions.updateSchedule({ enabled: false })
        await expectLogic(logic).toFinishAllListeners()
        expect(dataCatalogMetricsChecksScheduleRetrieve).not.toHaveBeenCalled()
        expect(logic.values.scheduleError).toEqual({
            message: 'You do not have permission to perform this action.',
            uncertain: false,
        })
        expect(logic.values.schedule?.enabled).toBe(true)
    })

    it('does not overwrite a completed edit with an older refresh response', async () => {
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        let resolveRefresh!: (schedule: typeof SCHEDULE) => void
        ;(dataCatalogMetricsChecksScheduleRetrieve as jest.Mock).mockReturnValueOnce(
            new Promise((resolve) => {
                resolveRefresh = resolve
            })
        )
        logic.actions.refreshSchedule()
        ;(dataCatalogMetricsChecksSchedulePartialUpdate as jest.Mock).mockResolvedValue({ ...SCHEDULE, enabled: false })
        await expectLogic(logic, () => logic.actions.updateSchedule({ enabled: false })).toDispatchActions([
            'updateScheduleSuccess',
        ])
        resolveRefresh(SCHEDULE)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.schedule?.enabled).toBe(false)
    })

    it('refreshes the schedule while the frequency controls are open', async () => {
        let refreshSchedule: (() => void) | undefined
        const setIntervalSpy = jest.spyOn(window, 'setInterval').mockImplementation((handler: TimerHandler) => {
            refreshSchedule = handler as () => void
            return 1
        })
        ;(dataCatalogMetricsChecksScheduleRetrieve as jest.Mock)
            .mockResolvedValueOnce(SCHEDULE)
            .mockResolvedValueOnce({ ...SCHEDULE, next_run_at: '2026-09-06T00:00:00Z' })

        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.schedule?.next_run_at).toBe('2026-09-05T00:00:00Z')

        refreshSchedule?.()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.schedule?.next_run_at).toBe('2026-09-06T00:00:00Z')

        setIntervalSpy.mockRestore()
    })
})
