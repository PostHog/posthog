import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import {
    accountsEmailThreadsList,
    accountsEmailThreadsRetrieve,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountEmailThreadApi,
    AccountEmailThreadDetailApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountEmailThreadsLogic, PAGE_SIZE } from './accountEmailThreadsLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsEmailThreadsList: jest.fn(),
    accountsEmailThreadsRetrieve: jest.fn(),
}))

const mockList = accountsEmailThreadsList as jest.MockedFunction<typeof accountsEmailThreadsList>
const mockRetrieve = accountsEmailThreadsRetrieve as jest.MockedFunction<typeof accountsEmailThreadsRetrieve>

const thread = {
    id: '11111111-1111-1111-1111-111111111111',
    subject: 'Account review',
    preview: 'Latest message',
    first_message_at: '2026-08-01T10:00:00Z',
    last_message_at: '2026-08-01T11:00:00Z',
    message_count: 2,
    participants: [],
} as AccountEmailThreadApi

const detail = {
    ...thread,
    messages: [
        {
            id: '22222222-2222-2222-2222-222222222222',
            sent_at: '2026-08-01T10:00:00Z',
            sender: { name: 'Customer', email: 'customer@example.com' },
            to_recipients: [],
            cc_recipients: [],
            sender_authenticated: true,
            direction: 'inbound',
            content: 'Message body',
        },
    ],
} as AccountEmailThreadDetailApi

describe('accountEmailThreadsLogic', () => {
    let logic: ReturnType<typeof accountEmailThreadsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        jest.spyOn(posthog, 'captureException').mockReturnValue(undefined as any)
        mockList.mockResolvedValue({ count: 1, next: null, previous: null, results: [thread] })
    })

    afterEach(() => {
        logic?.unmount()
    })

    const mount = async (): Promise<void> => {
        logic = accountEmailThreadsLogic({ accountId: 'acc-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('paginates summaries and loads message detail only when a thread opens', async () => {
        mockRetrieve.mockResolvedValue(detail)
        await mount()

        expect(mockRetrieve).not.toHaveBeenCalled()
        await expectLogic(logic, () => logic.actions.openThread(thread.id)).toFinishAllListeners()
        expect(logic.values.threadDetails[thread.id]).toEqual(detail)
        expect(mockRetrieve).toHaveBeenCalledTimes(1)

        logic.actions.closeThread(thread.id)
        await expectLogic(logic, () => logic.actions.openThread(thread.id)).toFinishAllListeners()
        expect(mockRetrieve).toHaveBeenCalledTimes(1)

        await expectLogic(logic, () => logic.actions.setPage(2)).toFinishAllListeners()
        expect(mockList).toHaveBeenLastCalledWith(expect.any(String), 'acc-1', {
            limit: PAGE_SIZE,
            offset: PAGE_SIZE,
        })
    })

    it('records a detail error instead of leaving the expanded row loading', async () => {
        mockRetrieve.mockRejectedValue(new Error('network'))
        await mount()

        await expectLogic(logic, () => logic.actions.openThread(thread.id)).toFinishAllListeners()

        expect(logic.values.threadDetailsLoading[thread.id]).toBe(false)
        expect(logic.values.threadDetailErrors[thread.id]).toBe(true)
        expect(posthog.captureException).toHaveBeenCalledTimes(1)
    })
})
