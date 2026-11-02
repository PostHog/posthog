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

    it('does not load the summary again when the tab is shown after the first load', async () => {
        const setDocumentHidden = (hidden: boolean): void => {
            Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
            document.dispatchEvent(new Event('visibilitychange'))
        }
        await jest.advanceTimersByTimeAsync(5000)
        expect(getSpy).toHaveBeenCalledTimes(1)

        setDocumentHidden(true)
        setDocumentHidden(false)
        await jest.advanceTimersByTimeAsync(5000)

        expect(getSpy).toHaveBeenCalledTimes(1)
    })
})
