import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import {
    accountsEmailThreadsList,
    accountsSummariesList,
    accountsSupportTicketsList,
} from 'products/customer_analytics/frontend/generated/api'

import { accountConversationsLogic } from './accountConversationsLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsEmailThreadsList: jest.fn(),
    accountsSummariesList: jest.fn(),
    accountsSupportTicketsList: jest.fn(),
}))

const mockEmailThreads = accountsEmailThreadsList as jest.MockedFunction<typeof accountsEmailThreadsList>
const mockSummaries = accountsSummariesList as jest.MockedFunction<typeof accountsSummariesList>
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
                    last_message_at: '2026-08-03T09:00:00Z',
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
                deep_link: '/support/tickets/42',
                created_at: '2026-08-01T09:00:00Z',
                started_by: 'Example customer',
                distinct_id: 'customer@example.com',
            },
        ])
        mockSummaries.mockResolvedValue({
            count: 0,
            next: null,
            previous: null,
            results: [],
        })
    })

    afterEach(() => logic?.unmount())

    it('combines, sorts, searches, and filters conversations', async () => {
        logic = accountConversationsLogic({ accountId: 'account-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.filteredConversations.map((conversation) => conversation.source)).toEqual([
            'email',
            'support',
        ])

        logic.actions.setSearchTerm('support preview')
        expect(logic.values.filteredConversations.map((conversation) => conversation.source)).toEqual(['support'])

        logic.actions.setSearchTerm('')
        logic.actions.setSources(['email'])
        expect(logic.values.filteredConversations.map((conversation) => conversation.source)).toEqual(['email'])
    })
})
