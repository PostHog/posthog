import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import {
    accountsEmailThreadMessagesList,
    accountsEmailThreadsList,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountEmailThreadApi,
    PaginatedAccountEmailThreadMessageListApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountEmailThreadsLogic, MESSAGE_PAGE_SIZE, PAGE_SIZE } from './accountEmailThreadsLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsEmailThreadMessagesList: jest.fn(),
    accountsEmailThreadsList: jest.fn(),
}))

const mockList = accountsEmailThreadsList as jest.MockedFunction<typeof accountsEmailThreadsList>
const mockMessageList = accountsEmailThreadMessagesList as jest.MockedFunction<typeof accountsEmailThreadMessagesList>

const thread = {
    id: '11111111-1111-1111-1111-111111111111',
    subject: 'Account review',
    preview: 'Latest message',
    first_message_at: '2026-08-01T10:00:00Z',
    first_message: {
        sender: {
            name: 'Example customer',
            email: 'customer@example.com',
            person_id: null,
            distinct_id: null,
        },
        sent_at: '2026-08-01T10:00:00Z',
        direction: 'inbound',
    },
    last_message_at: '2026-08-01T11:00:00Z',
    last_message: {
        sender: {
            name: 'Account manager',
            email: 'manager@example.com',
            person_id: null,
            distinct_id: null,
        },
        sent_at: '2026-08-01T11:00:00Z',
        direction: 'outbound',
    },
    message_count: 2,
    participants: [],
} as AccountEmailThreadApi

const detail = {
    count: 1,
    next: null,
    previous: null,
    results: [
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
} as PaginatedAccountEmailThreadMessageListApi

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
        mockMessageList.mockResolvedValue(detail)
        await mount()

        expect(mockMessageList).not.toHaveBeenCalled()
        await expectLogic(logic, () => logic.actions.openThread(thread.id)).toFinishAllListeners()
        expect(logic.values.threadDetails[thread.id]).toEqual(detail)
        expect(mockMessageList).toHaveBeenCalledTimes(1)
        expect(mockMessageList).toHaveBeenLastCalledWith(expect.any(String), 'acc-1', thread.id, {
            limit: MESSAGE_PAGE_SIZE,
            offset: 0,
        })

        await expectLogic(logic, () => logic.actions.setThreadDetailPage(thread.id, 2)).toFinishAllListeners()
        expect(mockMessageList).toHaveBeenCalledTimes(2)
        expect(mockMessageList).toHaveBeenLastCalledWith(expect.any(String), 'acc-1', thread.id, {
            limit: MESSAGE_PAGE_SIZE,
            offset: MESSAGE_PAGE_SIZE,
        })

        logic.actions.closeThread(thread.id)
        await expectLogic(logic, () => logic.actions.openThread(thread.id)).toFinishAllListeners()
        expect(mockMessageList).toHaveBeenCalledTimes(2)

        await expectLogic(logic, () => logic.actions.setPage(2)).toFinishAllListeners()
        expect(mockList).toHaveBeenLastCalledWith(expect.any(String), 'acc-1', {
            limit: PAGE_SIZE,
            offset: PAGE_SIZE,
        })
    })

    it('records a detail error instead of leaving the expanded row loading', async () => {
        mockMessageList.mockRejectedValue(new Error('network'))
        await mount()

        await expectLogic(logic, () => logic.actions.openThread(thread.id)).toFinishAllListeners()

        expect(logic.values.threadDetailsLoading[thread.id]).toBe(false)
        expect(logic.values.threadDetailErrors[thread.id]).toBe(true)
        expect(posthog.captureException).toHaveBeenCalledTimes(1)
    })
})
