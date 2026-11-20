import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { accountsAutomationsList } from '../../generated/api'
import { accountAutomationsLogic, AUTOMATIONS_PAGE_SIZE } from './accountAutomationsLogic'

jest.mock('../../generated/api', () => ({
    ...jest.requireActual('../../generated/api'),
    accountsAutomationsList: jest.fn(),
}))

const listRuns = jest.mocked(accountsAutomationsList)

describe('accountAutomationsLogic', () => {
    let logic: ReturnType<typeof accountAutomationsLogic.build>

    beforeEach(() => {
        initKeaTests()
        listRuns.mockReset()
    })
    afterEach(() => logic?.unmount())

    it('loads on opening and fetches the next server page', async () => {
        listRuns.mockResolvedValue({ results: [], count: 25, next: null, previous: null })
        logic = accountAutomationsLogic({ accountId: 'account' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.runs?.count).toBe(25)

        logic.actions.setPage(2)
        await expectLogic(logic).toFinishAllListeners()
        expect(listRuns).toHaveBeenLastCalledWith(expect.any(String), 'account', {
            limit: AUTOMATIONS_PAGE_SIZE,
            offset: AUTOMATIONS_PAGE_SIZE,
        })
    })

    it('shows a failed load and clears it after retry', async () => {
        listRuns.mockRejectedValueOnce(new Error('Network unavailable'))
        logic = accountAutomationsLogic({ accountId: 'account' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.loadFailed).toBe(true)
        expect(logic.values.runsLoading).toBe(false)
        expect(logic.values.runs).toBeNull()

        listRuns.mockResolvedValue({ results: [], count: 0, next: null, previous: null })
        logic.actions.loadRuns()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.loadFailed).toBe(false)
        expect(logic.values.runs?.count).toBe(0)
    })

    it.each(['success', 'failure'])('discards a superseded page %s', async (outcome) => {
        listRuns.mockResolvedValue({ results: [], count: 25, next: null, previous: null })
        logic = accountAutomationsLogic({ accountId: 'account' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        let settle!: () => void
        listRuns.mockImplementationOnce(
            () =>
                new Promise((resolve, reject) => {
                    settle = () => {
                        if (outcome === 'success') {
                            resolve({ results: [], count: 10, next: null, previous: null })
                        } else {
                            reject(new Error('Superseded request failed'))
                        }
                    }
                })
        )
        await expectLogic(logic, () => logic.actions.setPage(2)).toDispatchActions(['loadRuns'])
        await expectLogic(logic, () => logic.actions.setPage(3)).toDispatchActions(['loadRunsSuccess'])
        settle()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.page).toBe(3)
        expect(logic.values.runs?.count).toBe(25)
        expect(logic.values.loadFailed).toBe(false)
        expect(logic.values.runsLoading).toBe(false)
    })
})
