import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { healthSummaryLogic } from './healthSummaryLogic'

describe('healthSummaryLogic', () => {
    let logic: ReturnType<typeof healthSummaryLogic.build>
    let getSpy: jest.SpyInstance

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        getSpy = jest.spyOn(api, 'get').mockResolvedValue({ unsnoozed: { total: 2 }, snoozed: { total: 0 } })
        logic = healthSummaryLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('loads the summary after boot instead of on mount', async () => {
        expect(getSpy).not.toHaveBeenCalled()

        await jest.advanceTimersByTimeAsync(5000)

        expect(getSpy).toHaveBeenCalledTimes(1)
        expect(getSpy).toHaveBeenCalledWith(expect.stringContaining('/health_issues/summary/'))
        expect(logic.values.unsnoozedCount).toBe(2)
    })
})
