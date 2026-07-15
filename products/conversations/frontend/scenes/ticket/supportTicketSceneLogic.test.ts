import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import type { CommentType } from '~/types'

import type { Ticket } from '../../types'
import { EmailReplyBlockedReason, getEmailReplyBlockedReason, supportTicketSceneLogic } from './supportTicketSceneLogic'

const FEEDBACK_STORAGE_KEY = 'conversations_ai_reply_feedback'

jest.mock('~/lib/api', () => {
    const actual = jest.requireActual('~/lib/api')
    return {
        __esModule: true,
        default: {
            ...actual.default,
            conversationsTickets: {
                ...actual.default?.conversationsTickets,
                submitAiFeedback: jest.fn().mockResolvedValue(undefined),
            },
        },
    }
})

import api from '~/lib/api'

const submitAiFeedbackMock = api.conversationsTickets.submitAiFeedback as jest.Mock

function makeAiComment(id: string): CommentType {
    return {
        id,
        content: 'AI reply body',
        scope: 'conversations_ticket',
        item_id: 'ticket-1',
        item_context: { author_type: 'AI', is_private: true },
        created_at: '2026-01-01T00:00:00Z',
        created_by: null,
    } as unknown as CommentType
}

function makeTicket(): Ticket {
    return {
        id: 'ticket-1',
        ticket_number: 42,
        distinct_id: 'user-1',
        status: 'open',
        channel_source: 'widget',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        message_count: 1,
        ai_triage: {
            status: 'done',
            result: 'persisted',
            confidence: 0.92,
            ai_trace_id: 'trace-abc',
        },
    } as Ticket
}

describe('supportTicketSceneLogic ai reply feedback', () => {
    let logic: ReturnType<typeof supportTicketSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        localStorage.removeItem(FEEDBACK_STORAGE_KEY)
        submitAiFeedbackMock.mockClear()
        logic = supportTicketSceneLogic({ id: 'new' })
        logic.mount()
        logic.actions.setTicket(makeTicket())
        logic.actions.setMessages([makeAiComment('msg-ai-1')])
    })

    afterEach(() => {
        localStorage.removeItem(FEEDBACK_STORAGE_KEY)
    })

    it('selects the latest AI message', async () => {
        await expectLogic(logic).toMatchValues({
            latestAiMessage: expect.objectContaining({ id: 'msg-ai-1', authorType: 'AI' }),
        })
    })

    it('calls backend relay on good feedback', async () => {
        await expectLogic(logic, () => {
            logic.actions.submitAiReplyFeedback('msg-ai-1', 'good')
        })
            .toDispatchActions(['recordAiReplyFeedback'])
            .toMatchValues({
                feedbackByMessageId: { 'msg-ai-1': 'good' },
            })

        expect(submitAiFeedbackMock).toHaveBeenCalledTimes(1)
        expect(submitAiFeedbackMock).toHaveBeenCalledWith('ticket-1', {
            message_id: 'msg-ai-1',
            rating: 'good',
        })
    })

    it('calls backend relay on bad rating and feedback text separately', async () => {
        await expectLogic(logic, () => {
            logic.actions.submitAiReplyFeedback('msg-ai-1', 'bad')
        })
            .toDispatchActions(['recordAiReplyFeedback'])
            .toMatchValues({
                feedbackByMessageId: { 'msg-ai-1': 'bad' },
            })

        expect(submitAiFeedbackMock).toHaveBeenCalledTimes(1)
        expect(submitAiFeedbackMock).toHaveBeenCalledWith('ticket-1', {
            message_id: 'msg-ai-1',
            rating: 'bad',
        })

        submitAiFeedbackMock.mockClear()

        logic.actions.submitAiReplyFeedback('msg-ai-1', 'bad', 'Wrong answer')

        // Wait for async listener
        await new Promise((r) => setTimeout(r, 10))

        expect(submitAiFeedbackMock).toHaveBeenCalledTimes(1)
        expect(submitAiFeedbackMock).toHaveBeenCalledWith('ticket-1', {
            message_id: 'msg-ai-1',
            rating: 'bad',
            feedback_text: 'Wrong answer',
        })
    })

    it('dedupes repeated rating submissions for the same message', async () => {
        logic.actions.submitAiReplyFeedback('msg-ai-1', 'good')

        // Wait for async listener
        await new Promise((r) => setTimeout(r, 10))
        submitAiFeedbackMock.mockClear()

        logic.actions.submitAiReplyFeedback('msg-ai-1', 'bad')

        // Wait for async listener
        await new Promise((r) => setTimeout(r, 10))

        expect(submitAiFeedbackMock).not.toHaveBeenCalled()
        expect(logic.values.feedbackByMessageId['msg-ai-1']).toBe('good')
    })
})

type GateTicket = Pick<Ticket, 'channel_source' | 'email_from' | 'email_to'>

const emailTicket = (overrides: Partial<GateTicket> = {}): GateTicket => ({
    channel_source: 'email',
    email_from: 'customer@example.com',
    email_to: 'support@example.com',
    ...overrides,
})

describe('getEmailReplyBlockedReason', () => {
    // Each gate mirrors a backend condition that silently drops delivery: removing one
    // reintroduces replies that save as comments but never reach the customer, while
    // breaking the channel_source guard would disable the reply box on non-email tickets.
    test.each<[string, GateTicket | null, { email_enabled?: boolean } | null, EmailReplyBlockedReason | null]>([
        ['widget tickets are never blocked', emailTicket({ channel_source: 'widget' }), null, null],
        ['no ticket loaded yet', null, { email_enabled: true }, null],
        ['email disabled on team', emailTicket(), { email_enabled: false }, 'email_disabled'],
        ['conversations settings missing', emailTicket(), null, 'email_disabled'],
        [
            'no customer address (e.g. imported ticket with deleted requester)',
            emailTicket({ email_from: null }),
            { email_enabled: true },
            'no_recipient',
        ],
        [
            'no email channel attached (e.g. imported ticket without default inbox)',
            emailTicket({ email_to: null }),
            { email_enabled: true },
            'no_channel',
        ],
        ['fully configured email ticket', emailTicket(), { email_enabled: true }, null],
    ])('%s', (_name, ticket, settings, expected) => {
        expect(getEmailReplyBlockedReason(ticket, settings)).toBe(expected)
    })
})
