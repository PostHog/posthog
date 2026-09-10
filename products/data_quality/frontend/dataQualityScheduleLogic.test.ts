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
        expect(logic.values.scheduleError).toBeTruthy()
        expect(logic.values.scheduleLoading).toBe(false)
    })
})
