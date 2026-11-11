import { expectLogic } from 'kea-test-utils'

import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { accountAgentActivityLogic } from './accountAgentActivityLogic'

jest.mock('~/queries/query', () => ({ performQuery: jest.fn() }))
const mockPerformQuery = performQuery as jest.Mock

describe('accountAgentActivityLogic', () => {
    beforeEach(() => {
        initKeaTests()
        mockPerformQuery.mockReset()
        mockPerformQuery.mockResolvedValue({ results: { buckets: [] } })
    })

    it.each([
        ['a saved range', { weeks: '12' }, 12],
        ['a stale range', { weeks: '5' }, 8],
        ['no saved range', undefined, 8],
    ])('starts from %s, then saves and reloads a new one', async (_, initialConfig, startWeeks) => {
        const onConfigChange = jest.fn()
        const logic = accountAgentActivityLogic({
            accountId: 'account-1',
            instanceId: 'tile-one',
            initialConfig,
            onConfigChange,
        })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadResultSuccess'])

        await expectLogic(logic, () => logic.actions.setWeeks(26)).toDispatchActions(['loadResultSuccess'])

        expect(mockPerformQuery.mock.calls.map(([query]) => [query.accountId, query.weeks])).toEqual([
            ['account-1', startWeeks],
            ['account-1', 26],
        ])
        expect(onConfigChange).toHaveBeenCalledTimes(1)
        expect(onConfigChange).toHaveBeenCalledWith({ weeks: '26' })
        logic.unmount()
    })
})
