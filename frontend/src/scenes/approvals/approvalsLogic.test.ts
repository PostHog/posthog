import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { AvailableFeature, ChangeRequestState } from '~/types'

import { approvalsLogic } from './approvalsLogic'

describe('approvalsLogic', () => {
    let listGet: jest.SpyInstance

    const changeRequestRequests = (): string[] =>
        listGet.mock.calls.map(([url]) => String(url)).filter((url) => url.includes('/change_requests/'))

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        listGet = jest.spyOn(api, 'get').mockResolvedValue({ results: [], count: 0 })
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            organization: {
                ...MOCK_DEFAULT_ORGANIZATION,
                available_product_features: [{ key: AvailableFeature.APPROVALS, name: 'Approvals' }],
            },
        })
    })

    afterEach(() => {
        listGet.mockRestore()
        jest.useRealTimers()
    })

    it.each<[string, (logic: ReturnType<typeof approvalsLogic.build>) => Promise<void>]>([
        ['the list opens', async (logic) => void logic.mount()],
        [
            'the state filter changes',
            async (logic) => {
                logic.mount()
                await jest.advanceTimersByTimeAsync(1000)
                listGet.mockClear()
                logic.actions.setFilters({ state: ChangeRequestState.Applied })
            },
        ],
    ])('sends the change request list request at once when %s', async (_, act) => {
        await act(approvalsLogic())

        expect(changeRequestRequests()).toHaveLength(1)
    })
})
