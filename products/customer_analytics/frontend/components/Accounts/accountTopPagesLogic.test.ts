import { expectLogic } from 'kea-test-utils'

import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { accountTopPagesLogic } from './accountTopPagesLogic'

jest.mock('~/queries/query', () => ({ performQuery: jest.fn() }))
const mockPerformQuery = performQuery as jest.Mock

describe('accountTopPagesLogic', () => {
    beforeEach(() => {
        initKeaTests()
        mockPerformQuery.mockReset()
        mockPerformQuery.mockResolvedValue({ results: { pages: [] } })
    })

    it('restores both saved settings and saves the whole config on each change', async () => {
        const onConfigChange = jest.fn()
        const logic = accountTopPagesLogic({
            accountId: 'account-1',
            instanceId: 'tile-one',
            initialConfig: { weeks: '4', productKey: 'flags' },
            onConfigChange,
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadResultSuccess'])
        expect(mockPerformQuery.mock.calls[0][0].weeks).toBe(4)

        logic.actions.setWeeks(12)
        expect(onConfigChange).toHaveBeenLastCalledWith({ weeks: '12', productKey: 'flags' })
        logic.actions.setProductKey(null)
        expect(onConfigChange).toHaveBeenLastCalledWith({ weeks: '12' })
        await expectLogic(logic).toDispatchActions(['loadResultSuccess'])
        expect(mockPerformQuery).toHaveBeenCalledTimes(2)
        logic.unmount()
    })
})
