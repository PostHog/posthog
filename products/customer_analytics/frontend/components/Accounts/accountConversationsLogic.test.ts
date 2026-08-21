import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import {
    accountsEmailThreadsList,
    accountsSummariesList,
    accountsSupportTicketMessagesList,
    accountsSupportTicketsList,
} from 'products/customer_analytics/frontend/generated/api'

import { accountConversationsLogic } from './accountConversationsLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsEmailThreadsList: jest.fn(),
    accountsSummariesList: jest.fn(),
    accountsSupportTicketMessagesList: jest.fn(),
    accountsSupportTicketsList: jest.fn(),
}))

const mockEmailThreads = accountsEmailThreadsList as jest.MockedFunction<typeof accountsEmailThreadsList>
const mockSummaries = accountsSummariesList as jest.MockedFunction<typeof accountsSummariesList>
const mockSupportTicketMessages = accountsSupportTicketMessagesList as jest.MockedFunction<
    typeof accountsSupportTicketMessagesList
>
const mockSupportTickets = accountsSupportTicketsList as jest.MockedFunction<typeof accountsSupportTicketsList>

describe('accountConversationsLogic', () => {
    let logic: ReturnType<typeof accountConversationsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        jest.spyOn(posthog, 'captureException').mockReturnValue(undefined as any)
        mockEmailThreads.mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: [
                {
                    id: '11111111-1111-1111-1111-111111111111',
                    subject: 'Renewal planning',
                    preview: 'Latest email',
                    first_message_at: '2026-08-01T09:00:00Z',
                    first_message: {
                        sender: {
                            name: 'Example customer',
                            email: 'customer@example.com',
                            person_id: null,
                            distinct_id: null,
                        },
                        sent_at: '2026-08-01T09:00:00Z',
                        direction: 'inbound',
                    },
                    last_message_at: '2026-08-03T09:00:00Z',
                    last_message: {
                        sender: {
                            name: 'Account manager',
                            email: 'manager@example.com',
                            person_id: null,
                            distinct_id: null,
                        },
                        sent_at: '2026-08-03T09:00:00Z',
                        direction: 'outbound',
                    },
                    message_count: 2,
                    participants: [],
                },
            ],
        })
        mockSupportTickets.mockResolvedValue([
            {
                id: 'ticket-1',
                ticket_number: 42,
                status: 'open',
                last_message_at: '2026-08-02T09:00:00Z',
                last_message_text: 'Support preview',
                last_message: {
                    sender: {
                        name: 'Example customer',
                        email: 'customer@example.com',
                        person_id: null,
                        distinct_id: 'customer@example.com',
                    },
                    sent_at: '2026-08-02T09:00:00Z',
                    direction: 'inbound',
                },
                deep_link: '/support/tickets/42',
                created_at: '2026-08-01T09:00:00Z',
                started_by: 'Example customer',
                distinct_id: 'customer@example.com',
            },
        ])
        mockSupportTicketMessages.mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: [
                {
                    id: '33333333-3333-3333-3333-333333333333',
                    content: 'Support reply',
                    author_name: 'Account manager',
                    direction: 'outbound',
                    is_private: false,
                    created_at: '2026-08-02T10:00:00Z',
                },
            ],
        })
        mockSummaries.mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: [
                {
                    id: '22222222-2222-2222-2222-222222222222',
                    slack_channel_id: 'C012345',
                    cadence: 'weekly',
                    period_start: '2026-08-01T00:00:00Z',
                    period_end: '2026-08-10T00:00:00Z',
                    content: 'Slack summary',
                    message_count: 2,
                    messages: [
                        {
                            author: 'Example customer',
                            sent_at: '2026-08-01T12:00:00Z',
                            permalink: 'https://example.com/slack/1',
                        },
                        {
                            author: 'Account manager',
                            sent_at: '2026-08-02T12:00:00Z',
                            permalink: 'https://example.com/slack/2',
                        },
                    ],
                    generated_at: '2026-08-10T01:00:00Z',
                },
            ],
        })
    })

    afterEach(() => logic?.unmount())

    it('combines, sorts, searches, and filters conversations', async () => {
        logic = accountConversationsLogic({ accountId: 'account-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.filteredConversations.map((conversation) => conversation.source)).toEqual([
            'slack',
            'email',
            'support',
        ])
        expect(
            logic.values.filteredConversations.find((conversation) => conversation.source === 'slack')?.occurredAt
        ).toBe('2026-08-10T01:00:00Z')

        logic.actions.setSearchTerm('support preview')
        expect(logic.values.filteredConversations.map((conversation) => conversation.source)).toEqual(['support'])

        logic.actions.setSearchTerm('Account manager')
        expect(logic.values.filteredConversations.map((conversation) => conversation.source)).toEqual(['slack'])

        logic.actions.setSearchTerm('')
        logic.actions.setSources(['email'])
        expect(logic.values.filteredConversations.map((conversation) => conversation.source)).toEqual(['email'])

        logic.actions.openConversation('support:ticket-1')
        await expectLogic(logic).toFinishAllListeners()
        expect(mockSupportTicketMessages).toHaveBeenCalledWith('997', 'account-1', 'ticket-1', {
            limit: 200,
            offset: 0,
        })
        expect(logic.values.supportTicketMessages['ticket-1'].results[0].content).toBe('Support reply')

        expect(logic.values.expandedSummaryMessageIds['22222222-2222-2222-2222-222222222222']).toBeUndefined()
        logic.actions.toggleSummaryMessages('22222222-2222-2222-2222-222222222222')
        expect(logic.values.expandedSummaryMessageIds['22222222-2222-2222-2222-222222222222']).toBe(true)
    })

    it('keeps available conversations and retries a forbidden source', async () => {
        const supportTickets = await mockSupportTickets('997', 'account-1')
        jest.clearAllMocks()
        mockSupportTickets.mockRejectedValueOnce(new ApiError('Forbidden', 403)).mockResolvedValueOnce(supportTickets)
        logic = accountConversationsLogic({ accountId: 'account-1' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.conversationsResult.failedSources).toEqual(['support'])
        expect(logic.values.filteredConversations.map(({ source }) => source)).toEqual(['slack', 'email'])
        expect(logic.values.conversationsResult.loadFailed).toBeUndefined()
        expect(posthog.captureException).not.toHaveBeenCalled()

        await expectLogic(logic, () => logic.actions.loadConversations()).toFinishAllListeners()

        expect(logic.values.conversationsResult.failedSources).toEqual([])
        expect(logic.values.filteredConversations.map(({ source }) => source)).toEqual(['slack', 'email', 'support'])
    })

    it('loads older paginated conversations without replacing the current timeline', async () => {
        const firstPage = await mockSummaries('997', 'account-1', { limit: 50, offset: 0 })
        const olderSummary = {
            ...firstPage.results[0],
            id: '44444444-4444-4444-4444-444444444444',
            content: 'Older Slack summary',
            generated_at: '2026-07-10T01:00:00Z',
        }
        jest.clearAllMocks()
        mockSummaries
            .mockResolvedValueOnce({ ...firstPage, count: 2 })
            .mockRejectedValueOnce(new Error('network'))
            .mockResolvedValueOnce({ ...firstPage, count: 2, results: [olderSummary] })
        logic = accountConversationsLogic({ accountId: 'account-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.olderConversationCount).toBe(1)
        await expectLogic(logic, () => logic.actions.loadMoreConversations()).toFinishAllListeners()
        expect(logic.values.conversationsResult.failedSources).toEqual(['slack'])
        expect(logic.values.olderConversationCount).toBe(1)

        await expectLogic(logic, () => logic.actions.loadMoreConversations()).toFinishAllListeners()

        expect(mockSummaries).toHaveBeenLastCalledWith('997', 'account-1', { limit: 50, offset: 1 })
        expect(logic.values.conversationsResult.failedSources).toEqual([])
        expect(logic.values.olderConversationCount).toBe(0)
        expect(logic.values.conversationsResult.conversations?.map(({ id }) => id)).toContain(
            'slack:44444444-4444-4444-4444-444444444444'
        )
    })
})
