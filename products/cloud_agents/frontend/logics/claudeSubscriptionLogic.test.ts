import { ApiError } from 'lib/api-error'

import {
    usersIntegrationsClaudeSubscriptionCreate,
    usersIntegrationsClaudeSubscriptionRetrieve,
} from '~/generated/core/api'
import type { UserClaudeSubscriptionApi } from '~/generated/core/api.schemas'
import { initKeaTests } from '~/test/init'

import { claudeSubscriptionLogic } from './claudeSubscriptionLogic'

jest.mock('~/generated/core/api')

const retrieveSubscription = jest.mocked(usersIntegrationsClaudeSubscriptionRetrieve)
const createSubscription = jest.mocked(usersIntegrationsClaudeSubscriptionCreate)

const NOT_CONNECTED: UserClaudeSubscriptionApi = {
    status: 'not_connected',
    token_suffix: null,
    connected_at: null,
    last_used_at: null,
}
const CONNECTED: UserClaudeSubscriptionApi = {
    status: 'connected',
    token_suffix: '0003',
    connected_at: '2026-09-01T10:00:00Z',
    last_used_at: null,
}
const FAKE_TOKEN = 'sk-ant-oat01-not-a-real-token-0003'

describe('claudeSubscriptionLogic', () => {
    let logic: ReturnType<typeof claudeSubscriptionLogic.build>

    beforeEach(async () => {
        jest.useFakeTimers()
        initKeaTests()
        retrieveSubscription.mockResolvedValue(NOT_CONNECTED)
        logic = claudeSubscriptionLogic()
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
        jest.resetAllMocks()
    })

    it('sends the trimmed token once, then closes the dialog and forgets the token', async () => {
        createSubscription.mockResolvedValue(CONNECTED)
        logic.actions.openConnectModal()
        logic.actions.setToken(`  ${FAKE_TOKEN}\n`)
        logic.actions.submitToken()
        logic.actions.submitToken()
        await jest.advanceTimersByTimeAsync(0)

        expect(createSubscription).toHaveBeenCalledTimes(1)
        expect(createSubscription).toHaveBeenCalledWith('@me', { token: FAKE_TOKEN })
        expect(logic.values).toMatchObject({ connected: true, connectModalOpen: false, token: '', connectError: null })
    })

    it('asks for a token and sends no request when the field is empty', async () => {
        logic.actions.openConnectModal()
        logic.actions.setToken('   ')
        logic.actions.submitToken()
        await jest.advanceTimersByTimeAsync(0)

        expect(createSubscription).not.toHaveBeenCalled()
        expect(logic.values.connectError).toBe('Paste the token first.')
    })

    it.each([
        [400, 'A Claude subscription token starts with `sk-ant-oat`.', 'starts with `sk-ant-oat`'],
        [404, 'Not found.', 'cannot connect a Claude subscription yet'],
    ])('keeps the dialog open with a message when the server answers %s', async (status, detail, message) => {
        createSubscription.mockRejectedValue(new ApiError(detail, status, undefined, { detail }))
        logic.actions.openConnectModal()
        logic.actions.setToken(FAKE_TOKEN)
        logic.actions.submitToken()
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values).toMatchObject({ connected: false, connectModalOpen: true, connecting: false })
        expect(logic.values.connectError).toContain(message)
    })
})
