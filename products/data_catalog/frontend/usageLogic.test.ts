import { ApiError } from 'lib/api'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { dataCatalogUsageLatestRetrieve, dataCatalogUsageList } from './generated/api'
import type { UsageSnapshotSummaryApi } from './generated/api.schemas'
import { usageLogic } from './usageLogic'

jest.mock('./generated/api', () => ({
    dataCatalogUsageList: jest.fn(),
    dataCatalogUsageLatestRetrieve: jest.fn(),
    dataCatalogUsageRecomputeCreate: jest.fn(),
}))

const scan = (status: UsageSnapshotSummaryApi['status']): UsageSnapshotSummaryApi =>
    ({ id: 'scan', status }) as UsageSnapshotSummaryApi

describe('usageLogic', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        jest.mocked(dataCatalogUsageLatestRetrieve).mockResolvedValue({} as any)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        [404, 'none', false],
        [500, null, true],
    ])('reads a %s answer for the latest scan', async (status, latest, loadFailed) => {
        jest.useRealTimers()
        jest.mocked(dataCatalogUsageList).mockResolvedValue([])
        jest.mocked(dataCatalogUsageLatestRetrieve).mockRejectedValue(new ApiError('nope', status))
        const logic = usageLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.latest).toBe(latest)
        expect(logic.values.latestLoadFailed).toBe(loadFailed)
    })

    it('keeps polling a running scan after a failed history request', async () => {
        jest.mocked(dataCatalogUsageList)
            .mockResolvedValueOnce([scan('computing')])
            .mockRejectedValueOnce(new Error('Bad gateway'))
            .mockResolvedValue([scan('done')])
        const logic = usageLogic()
        logic.mount()

        await jest.advanceTimersByTimeAsync(30_000)
        expect(dataCatalogUsageList).toHaveBeenCalledTimes(2)
        expect(logic.values.scanRunning).toBe(true)

        await jest.advanceTimersByTimeAsync(60_000)
        expect(dataCatalogUsageList).toHaveBeenCalledTimes(3)
        expect(logic.values.scanRunning).toBe(false)
    })

    it.each([
        [404, true],
        [500, false],
    ])('keeps the scan button off when the first history request fails (status %s)', async (status, unavailable) => {
        jest.mocked(dataCatalogUsageList).mockRejectedValue(new ApiError(undefined, status))
        const logic = usageLogic()
        logic.mount()

        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.usageUnavailable).toBe(unavailable)
        expect(logic.values.recomputeDisabledReason).not.toBeNull()
    })
})
