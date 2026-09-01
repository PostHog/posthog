import { MOCK_DEFAULT_USER } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { commentsLogic } from 'scenes/comments/commentsLogic'
import { userLogic } from 'scenes/userLogic'

import { tagsModel } from '~/models/tagsModel'
import { initKeaTests } from '~/test/init'
import type { CommentType } from '~/types'
import { ActivityScope } from '~/types'

import type { TicketAssignee } from '../../components/Assignee'
import type { Ticket, TicketStatus } from '../../types'
import { EmailReplyBlockedReason, getEmailReplyBlockedReason, supportTicketSceneLogic } from './supportTicketSceneLogic'

const FEEDBACK_STORAGE_KEY = 'conversations_ai_reply_feedback'

/** A logic left mounted keeps polling for messages, into whichever suite builds the same key next. */
function stopPolling(logic: ReturnType<typeof supportTicketSceneLogic.build> | undefined): void {
    if (logic?.isMounted()) {
        logic.unmount()
    }
}

jest.mock('~/lib/api', () => {
    const actual = jest.requireActual('~/lib/api')
    return {
        __esModule: true,
        default: {
            ...actual.default,
            createResponse: jest.fn(),
            comments: {
                ...actual.default?.comments,
                list: jest.fn().mockResolvedValue({ results: [] }),
            },
            persons: {
                ...actual.default?.persons,
                list: jest.fn().mockResolvedValue({ results: [] }),
            },
            conversationsTickets: {
                ...actual.default?.conversationsTickets,
                submitAiFeedback: jest.fn().mockResolvedValue(undefined),
                get: jest.fn(),
                update: jest.fn(),
                list: jest.fn().mockResolvedValue({ results: [] }),
            },
            tags: {
                ...actual.default?.tags,
                list: jest.fn().mockResolvedValue([]),
            },
        },
    }
})

jest.mock('products/business_knowledge/frontend/generated/api', () => ({
    businessKnowledgeGapSuggestionsList: jest.fn().mockResolvedValue({ results: [] }),
    businessKnowledgeGapSuggestionsDismissCreate: jest.fn().mockResolvedValue(undefined),
}))

jest.mock('products/conversations/frontend/generated/api', () => ({
    conversationsTicketsNotesPartialUpdate: jest.fn().mockResolvedValue(undefined),
    conversationsTicketsNotesDestroy: jest.fn().mockResolvedValue(undefined),
    conversationsTicketsPartialUpdate: jest.fn(),
}))

import api from '~/lib/api'

import {
    conversationsTicketsNotesPartialUpdate,
    conversationsTicketsPartialUpdate,
} from 'products/conversations/frontend/generated/api'

const submitAiFeedbackMock = api.conversationsTickets.submitAiFeedback as jest.Mock

function makeAiComment(id: string, isPrivate: boolean = true): CommentType {
    return {
        id,
        content: 'AI reply body',
        scope: 'conversations_ticket',
        item_id: 'ticket-1',
        item_context: { author_type: 'AI', is_private: isPrivate },
        created_at: '2026-01-01T00:00:00Z',
        created_by: null,
    } as unknown as CommentType
}

function makeSupportComment(overrides: Partial<CommentType> = {}): CommentType {
    return {
        id: 'msg-sent-1',
        content: 'hello',
        rich_content: null,
        version: 0,
        scope: 'conversations_ticket',
        item_id: 'ticket-1',
        item_context: { author_type: 'support', is_private: false },
        created_at: '2026-01-01T00:00:10Z',
        created_by: MOCK_DEFAULT_USER,
        ...overrides,
    } as unknown as CommentType
}

function commentResponse(comment: CommentType, status: number = 201): Response {
    return { status, json: () => Promise.resolve(comment) } as unknown as Response
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
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PRODUCT_SUPPORT_AI_NOTES]: true })
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

function makeCustomerComment(id: string, itemContext: Record<string, any> = {}): CommentType {
    return {
        id,
        content: 'reply body',
        scope: 'conversations_ticket',
        item_id: 'ticket-1',
        item_context: { author_type: 'customer', ...itemContext },
        created_at: '2026-01-01T00:00:00Z',
        created_by: null,
    } as unknown as CommentType
}

describe('supportTicketSceneLogic chatMessages author attribution', () => {
    let logic: ReturnType<typeof supportTicketSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = supportTicketSceneLogic({ id: 'new' })
        logic.mount()
        logic.actions.setTicket({ ...makeTicket(), anonymous_traits: { name: 'Mark' } } as Ticket)
    })

    // A thread reply from a second Teams/Slack participant must show its own author,
    // not fall back to the ticket requester's name.
    test.each<[string, Record<string, any>, string]>([
        ['teams thread reply author', { teams_author_name: 'Chris' }, 'Chris'],
        ['slack thread reply author', { slack_author_name: 'Chris' }, 'Chris'],
        ['requester fallback without per-message author', {}, 'Mark'],
    ])('%s', (_name, itemContext, expectedName) => {
        logic.actions.setMessages([makeCustomerComment('msg-1', itemContext)])
        expect(logic.values.chatMessages[0].authorName).toBe(expectedName)
    })
})

describe('supportTicketSceneLogic AI note visibility', () => {
    let logic: ReturnType<typeof supportTicketSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = supportTicketSceneLogic({ id: 'new' })
        logic.mount()
        logic.actions.setTicket(makeTicket())
    })

    test.each<[string, boolean, boolean, string[]]>([
        ['hides AI private notes without the flag', false, true, ['msg-customer']],
        ['shows AI private notes with the flag', true, true, ['msg-customer', 'msg-ai']],
        ['keeps sent AI replies visible without the flag', false, false, ['msg-customer', 'msg-ai']],
    ])('%s', (_name, flagEnabled, isPrivate, expectedIds) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PRODUCT_SUPPORT_AI_NOTES]: flagEnabled })
        logic.actions.setMessages([makeCustomerComment('msg-customer'), makeAiComment('msg-ai', isPrivate)])

        expect(logic.values.chatMessages.map((m) => m.id)).toEqual(expectedIds)
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

describe('supportTicketSceneLogic replyRecipientDescription', () => {
    let logic: ReturnType<typeof supportTicketSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = supportTicketSceneLogic({ id: 'new' })
        logic.mount()
    })

    // This string is shown in the draft-mode "This will send to ..." confirmation. Regressions
    // that swap email_from (customer) for email_to (our sending identity), drop cc recipients, or
    // mislabel a channel would tell the agent they're sending somewhere they aren't.
    test.each<[string, Partial<Ticket>, string]>([
        [
            'email uses the customer address, not our sending identity',
            { channel_source: 'email', email_from: 'customer@example.com', email_to: 'support@example.com' },
            'customer@example.com',
        ],
        [
            'email includes cc participants',
            {
                channel_source: 'email',
                email_from: 'customer@example.com',
                cc_participants: ['cc1@example.com', 'cc2@example.com'],
            },
            'customer@example.com, cc1@example.com, cc2@example.com',
        ],
        ['slack', { channel_source: 'slack' }, 'the linked Slack thread'],
        ['teams', { channel_source: 'teams' }, 'the linked Microsoft Teams channel'],
        ['github', { channel_source: 'github' }, 'the linked GitHub issue'],
        ['widget', { channel_source: 'widget' }, 'the customer'],
    ])('%s', (_name, overrides, expected) => {
        logic.actions.setTicket({ ...makeTicket(), ...overrides })
        expect(logic.values.replyRecipientDescription).toBe(expected)
    })
})

describe('supportTicketSceneLogic sendMessage with statusAfterSend', () => {
    let logic: ReturnType<typeof supportTicketSceneLogic.build>

    const createResponseMock = api.createResponse as jest.Mock
    const ticketGetMock = api.conversationsTickets.get as jest.Mock
    const ticketUpdateMock = conversationsTicketsPartialUpdate as jest.Mock

    // Unlike makeTicket(), API responses always carry priority/assignee; without them the
    // hasUnsavedChanges comparison against the seeded local reducers never settles to false.
    const loadedTicket = (): Ticket => ({ ...makeTicket(), priority: 'medium', assignee: null }) as Ticket

    beforeEach(async () => {
        initKeaTests()
        createResponseMock.mockReset().mockResolvedValue(commentResponse(makeSupportComment()))
        ticketGetMock.mockReset().mockResolvedValue(loadedTicket())
        ticketUpdateMock.mockReset()
        // A non-'new', dash-free id: sendMessage early-returns on 'new' and loadTicket
        // treats ids containing '-' as UUIDs to redirect.
        logic = supportTicketSceneLogic({ id: 42 })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['setTicket'])
    })

    afterEach(() => {
        stopPolling(logic)
    })

    // "Send and set status" must persist through the same PATCH as the "Save changes" button,
    // and must never change who the ticket is assigned to.
    test.each<[string, TicketAssignee, TicketStatus]>([
        ['leaves an unassigned ticket unassigned', null, 'resolved'],
        ['keeps a role assignee', { type: 'role', id: 'role-1' }, 'on_hold'],
        ['keeps a user assignee', { type: 'user', id: 999 }, 'pending'],
    ])('%s', async (_name, presetAssignee, statusAfterSend) => {
        if (presetAssignee) {
            logic.actions.setAssignee(presetAssignee)
        }
        ticketUpdateMock.mockResolvedValue({ ...loadedTicket(), status: statusAfterSend, assignee: presetAssignee })

        await expectLogic(logic, () => {
            logic.actions.sendMessage('hello', null, false, undefined, statusAfterSend)
        }).toDispatchActions(['updateTicket', 'setTicket'])

        expect(ticketUpdateMock).toHaveBeenCalledWith(
            expect.any(String),
            '42',
            expect.objectContaining({ status: statusAfterSend, assignee: presetAssignee })
        )
        expect(logic.values.status).toBe(statusAfterSend)
        expect(logic.values.hasUnsavedChanges).toBe(false)
    })

    it('does not update the ticket when the send fails', async () => {
        createResponseMock.mockRejectedValue(new Error('request failed'))

        await expectLogic(logic, () => {
            logic.actions.sendMessage('hello', null, false, undefined, 'resolved')
        }).toFinishAllListeners()

        expect(ticketUpdateMock).not.toHaveBeenCalled()
        expect(logic.values.status).toBe('open')
    })

    // The send-and-set confirmation lists exactly the pending non-status edits; status is
    // excluded because that action overrides it anyway. Drift here silently persists edits
    // without warning (or prompts when there is nothing extra to save).
    test.each<[string, () => void, string[]]>([
        ['a priority edit', () => logic.actions.setPriority('high'), ['Priority: High']],
        ['a tags edit', () => logic.actions.setTags(['bug']), ['Tags: bug']],
        ['an assignee edit', () => logic.actions.setAssignee({ type: 'role', id: 'role-1' }), ['Assignee: updated']],
        ['a status-only edit', () => logic.actions.setStatus('pending'), []],
    ])('unsavedTicketChanges lists %s', (_name, applyEdit, expected) => {
        applyEdit()
        expect(logic.values.unsavedTicketChanges).toEqual(expected)
    })

    // Overlapping updates must serialize: the second PATCH waits for the first and carries the
    // newest local edits, and the first (stale) response must not clobber them via setTicket.
    it('serializes overlapping updates so the newest status wins', async () => {
        let resolveFirst: (() => void) | undefined
        ticketUpdateMock.mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    resolveFirst = () => resolve({ ...loadedTicket(), status: 'resolved' })
                })
        )
        ticketUpdateMock.mockImplementationOnce((_projectId: string, _id: string, data: Record<string, unknown>) =>
            Promise.resolve({ ...loadedTicket(), ...data })
        )

        logic.actions.setStatus('resolved')
        logic.actions.updateTicket()
        logic.actions.setStatus('pending')
        logic.actions.updateTicket()

        expect(ticketUpdateMock).toHaveBeenCalledTimes(1)
        resolveFirst?.()
        await expectLogic(logic).toFinishAllListeners()

        expect(ticketUpdateMock).toHaveBeenCalledTimes(2)
        expect(ticketUpdateMock).toHaveBeenLastCalledWith(
            expect.any(String),
            '42',
            expect.objectContaining({ status: 'pending' })
        )
        expect(logic.values.status).toBe('pending')
        expect(logic.values.ticketUpdating).toBe(false)
    })
})

describe('supportTicketSceneLogic send outcome handling', () => {
    let logic: ReturnType<typeof supportTicketSceneLogic.build>

    const createResponseMock = api.createResponse as jest.Mock
    const commentsListMock = api.comments.list as jest.Mock
    const ticketGetMock = api.conversationsTickets.get as jest.Mock
    const captureMock = posthog.capture as jest.Mock

    const loadedTicket = (): Ticket => ({ ...makeTicket(), priority: 'medium', assignee: null }) as Ticket

    const rejectWith = (status?: number): void => {
        createResponseMock.mockRejectedValue(Object.assign(new Error('send failed'), { status }))
    }

    beforeEach(async () => {
        initKeaTests()
        createResponseMock.mockReset().mockResolvedValue(commentResponse(makeSupportComment()))
        commentsListMock.mockReset().mockResolvedValue({ results: [] })
        ticketGetMock.mockReset().mockResolvedValue(loadedTicket())
        captureMock.mockClear()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        logic = supportTicketSceneLogic({ id: 42 })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['setTicket', 'setMessages'])
    })

    afterEach(() => {
        stopPolling(logic)
        // These cases point the shared mock at failures and pending promises, which would break
        // every later suite's initial message load.
        commentsListMock.mockReset().mockResolvedValue({ results: [] })
        createResponseMock.mockReset().mockResolvedValue(commentResponse(makeSupportComment()))
    })

    it('shows the sent message without waiting for the next poll', async () => {
        const onSuccess = jest.fn()

        await expectLogic(logic, () => {
            logic.actions.sendMessage('hello', null, false, onSuccess)
        }).toDispatchActions(['appendMessage'])

        expect(logic.values.messages.map((message) => message.id)).toEqual(['msg-sent-1'])
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(logic.values.messageSending).toBe(false)
    })

    it('flags a resend the server deduplicated instead of reporting it as sent', async () => {
        createResponseMock.mockResolvedValue(commentResponse(makeSupportComment(), 200))
        const onSuccess = jest.fn()

        await expectLogic(logic, () => {
            logic.actions.sendMessage('hello', null, false, onSuccess)
        }).toFinishAllListeners()

        expect(logic.values.messages.map((message) => message.id)).toEqual(['msg-sent-1'])
        expect(onSuccess).not.toHaveBeenCalled()
        expect(captureMock).toHaveBeenCalledWith('support reply send deduplicated', { is_private: false })
        expect(logic.values.messageSending).toBe(false)
    })

    // A poll that started before the send must not replace the list with its older snapshot.
    it('keeps the sent message when an in-flight poll resolves afterwards', async () => {
        let resolveStalePoll: ((value: { results: CommentType[] }) => void) | undefined
        commentsListMock.mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    resolveStalePoll = resolve
                })
        )

        logic.actions.loadMessages()
        await expectLogic(logic, () => {
            logic.actions.sendMessage('hello', null, false)
        }).toDispatchActions(['appendMessage'])

        resolveStalePoll?.({ results: [] })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.messages.map((message) => message.id)).toEqual(['msg-sent-1'])
    })

    // 429 and 4xx rejections happen before anything is written, so the operator can just resend.
    // Sending them down the recovery path would tell them to go check a thread that never changed.
    it.each<[string, number]>([
        ['throttled', 429],
        ['rejected', 400],
    ])('reports a %s send as a plain failure without looking at the thread', async (_name, status) => {
        rejectWith(status)
        commentsListMock.mockClear()
        const onSuccess = jest.fn()

        await expectLogic(logic, () => {
            logic.actions.sendMessage('hello', null, false, onSuccess)
        }).toFinishAllListeners()

        expect(commentsListMock).not.toHaveBeenCalled()
        expect(onSuccess).not.toHaveBeenCalled()
        expect(captureMock).not.toHaveBeenCalledWith('support reply send unconfirmed', expect.anything())
        expect(logic.values.messageSending).toBe(false)
    })

    // A response we never saw, a timeout, a 409 from the server's own dedupe guard, and a 5xx all
    // leave the same question open: did the message land? If it did, adopt it instead of telling the
    // operator to resend something the customer already received.
    it.each<[string, number | undefined]>([
        ['no response', undefined],
        ['a timeout', 408],
        ['a concurrent duplicate', 409],
        ['a server error', 503],
    ])('adopts the message that landed despite %s', async (_name, status) => {
        rejectWith(status)
        const landed = makeSupportComment({ id: 'msg-landed-1', created_at: new Date().toISOString() })
        commentsListMock.mockResolvedValue({ results: [landed] })
        const onSuccess = jest.fn()

        await expectLogic(logic, () => {
            logic.actions.sendMessage('hello', null, false, onSuccess)
        }).toDispatchActions(['appendMessage'])

        expect(logic.values.messages.map((message) => message.id)).toEqual(['msg-landed-1'])
        expect(onSuccess).toHaveBeenCalledTimes(1)
        expect(createResponseMock).toHaveBeenCalledTimes(1)
        expect(captureMock).not.toHaveBeenCalledWith('support reply send unconfirmed', expect.anything())
    })

    // Adopting a near-miss would show the operator the wrong message as theirs, so each of these
    // has to keep the outcome unresolved.
    it.each<[string, Partial<CommentType>]>([
        ['a different body', { content: 'something else' }],
        ['a private note rather than a reply', { item_context: { author_type: 'support', is_private: true } }],
        ['a colleague as the author', { created_by: { ...MOCK_DEFAULT_USER, id: 9999 } as any }],
        ['a timestamp outside the replay window', { created_at: '2026-01-01T00:00:10Z' }],
    ])('does not adopt a message with %s', async (_name, overrides) => {
        rejectWith(503)
        commentsListMock.mockResolvedValue({
            results: [makeSupportComment({ id: 'msg-other-1', created_at: new Date().toISOString(), ...overrides })],
        })
        const onSuccess = jest.fn()

        await expectLogic(logic, () => {
            logic.actions.sendMessage('hello', null, false, onSuccess)
        }).toFinishAllListeners()

        expect(logic.values.messages).toEqual([])
        expect(onSuccess).not.toHaveBeenCalled()
        expect(captureMock).toHaveBeenCalledWith('support reply send unconfirmed', {
            reason: 'server_error',
            is_private: false,
        })
    })

    it('leaves the outcome unresolved when the recovery lookup also fails', async () => {
        rejectWith(undefined)
        commentsListMock.mockRejectedValue(new Error('offline'))
        const onSuccess = jest.fn()

        await expectLogic(logic, () => {
            logic.actions.sendMessage('hello', null, false, onSuccess)
        }).toFinishAllListeners()

        expect(onSuccess).not.toHaveBeenCalled()
        expect(captureMock).toHaveBeenCalledWith('support reply send unconfirmed', {
            reason: 'network',
            is_private: false,
        })
        expect(logic.values.messageSending).toBe(false)
    })
})

describe('supportTicketSceneLogic tag pool refresh', () => {
    let logic: ReturnType<typeof supportTicketSceneLogic.build>

    const ticketGetMock = api.conversationsTickets.get as jest.Mock
    const ticketUpdateMock = conversationsTicketsPartialUpdate as jest.Mock
    const tagsListMock = api.tags.list as jest.Mock

    const loadedTicket = (): Ticket => ({ ...makeTicket(), priority: 'medium', assignee: null }) as Ticket

    beforeEach(async () => {
        initKeaTests()
        tagsListMock.mockReset().mockResolvedValue(['known'])
        ticketGetMock.mockReset().mockResolvedValue(loadedTicket())
        ticketUpdateMock.mockReset()
        // Prime the shared lazy-loaded tag pool so availableTags reflects the existing tags.
        tagsModel.mount()
        tagsModel.actions.loadTags()
        await expectLogic(tagsModel).toDispatchActions(['loadTagsSuccess'])
        logic = supportTicketSceneLogic({ id: 42 })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['setTicket'])
        expect(logic.values.availableTags).toEqual(['known'])
        // Wait out lazyLoaders' deferred refetch, or it lands mid-test and makes the assertions below vacuous.
        await expectLogic(tagsModel).toDispatchActions(['loadTagsSuccess'])
        tagsListMock.mockClear()
    })

    afterEach(() => {
        stopPolling(logic)
    })

    // A newly typed tag is created globally on save, so the shared pool must reload to surface it
    // on other tickets; an already-known tag needs no reload.
    it('reloads the shared tag pool when a new tag was saved', async () => {
        ticketUpdateMock.mockResolvedValue({ ...loadedTicket(), tags: ['known', 'brand-new'] })
        tagsListMock.mockResolvedValue(['known', 'brand-new'])

        logic.actions.setTags(['known', 'brand-new'])
        await expectLogic(logic, () => {
            logic.actions.updateTicket()
        }).toDispatchActions(['setTicket'])
        await expectLogic(tagsModel).toDispatchActions(['loadTagsSuccess'])

        expect(tagsListMock).toHaveBeenCalledTimes(1)
        expect(logic.values.availableTags).toEqual(['known', 'brand-new'])
    })

    it('does not reload the tag pool when all saved tags are already known', async () => {
        ticketUpdateMock.mockResolvedValue({ ...loadedTicket(), tags: ['known'] })

        logic.actions.setTags(['known'])
        await expectLogic(logic, () => {
            logic.actions.updateTicket()
        }).toDispatchActions(['setTicket'])

        expect(tagsListMock).not.toHaveBeenCalled()
        expect(logic.values.availableTags).toEqual(['known'])
    })
})

describe('supportTicketSceneLogic loadPreviousTickets email gating', () => {
    let logic: ReturnType<typeof supportTicketSceneLogic.build>

    const personsListMock = api.persons.list as jest.Mock
    const ticketsListMock = api.conversationsTickets.list as jest.Mock
    const ticketGetMock = api.conversationsTickets.get as jest.Mock

    beforeEach(() => {
        initKeaTests()
        // Person carries a customer-controlled properties.email distinct from the ticket's email_from,
        // so the assertions prove the match uses email_from (when verified) and never properties.email.
        personsListMock.mockReset().mockResolvedValue({
            results: [{ id: 'p1', distinct_ids: ['user-1'], properties: { email: 'analytics@example.com' } }],
        })
        ticketsListMock.mockReset().mockResolvedValue({ results: [] })
        ticketGetMock.mockReset()
    })

    afterEach(() => {
        stopPolling(logic)
    })

    // email_from is attacker-spoofable unless the ticket's identity is positively attested, and
    // person.properties.email is customer-controlled analytics with no trusted mapping. Only a
    // verified ticket may widen the match by email — otherwise a spoofed sender pulls another
    // customer's ticket history into their own view.
    test.each<[string, boolean | null, Record<string, string>]>([
        [
            'verified email ticket matches by email_from',
            true,
            { distinct_ids: 'user-1', emails: 'verified@example.com' },
        ],
        ['unverified ticket omits emails', false, { distinct_ids: 'user-1' }],
        ['unknown identity omits emails', null, { distinct_ids: 'user-1' }],
    ])('%s', async (_name, identity_verified, expectedParams) => {
        ticketGetMock.mockResolvedValue({
            ...makeTicket(),
            distinct_id: 'user-1',
            channel_source: 'email',
            email_from: 'verified@example.com',
            identity_verified,
        })

        logic = supportTicketSceneLogic({ id: 42 })

        await expectLogic(logic, () => {
            logic.mount()
        }).toDispatchActions(['loadPreviousTicketsSuccess'])

        expect(ticketsListMock).toHaveBeenLastCalledWith(expectedParams)
    })
})

describe('supportTicketSceneLogic private note editing', () => {
    let logic: ReturnType<typeof supportTicketSceneLogic.build>

    const ticketGetMock = api.conversationsTickets.get as jest.Mock
    const noteUpdateMock = conversationsTicketsNotesPartialUpdate as jest.Mock
    const createResponseMock = api.createResponse as jest.Mock

    const loadedTicket = (): Ticket => ({ ...makeTicket(), priority: 'medium', assignee: null }) as Ticket

    beforeEach(async () => {
        localStorage.clear()
        initKeaTests()
        noteUpdateMock.mockReset().mockResolvedValue(undefined)
        createResponseMock.mockReset().mockResolvedValue(commentResponse(makeSupportComment()))
        ticketGetMock.mockReset().mockResolvedValue(loadedTicket())
        logic = supportTicketSceneLogic({ id: 42 })
        logic.mount()
        // Wait for ticket + initial message load so a late setMessages([]) can't cancel an edit.
        await expectLogic(logic).toDispatchActions(['setTicket', 'setMessages'])
    })

    afterEach(() => {
        stopPolling(logic)
    })

    test('startEditingMessage stashes the in-progress draft and loads the note', async () => {
        const draft = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'wip' }] }] }
        logic.actions.setDraftContent(draft)
        logic.actions.setDraftIsPrivate(false)

        const noteRich = {
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'note body' }] }],
        }
        logic.actions.startEditingMessage({
            id: 'note-1',
            content: 'note body',
            richContent: noteRich,
            authorType: 'human',
            authorName: 'Me',
            createdBy: { id: 1 },
            createdAt: '2026-01-01T00:00:00Z',
            isPrivate: true,
            version: 0,
        })

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.editingMessageId).toBe('note-1')
        expect(logic.values.draftIsPrivate).toBe(true)
        expect(logic.values.draftContent).toEqual(noteRich)
        expect(logic.values.stashedDraftContent).toEqual(draft)
        expect(logic.values.stashedDraftIsPrivate).toBe(false)
    })

    test('cancelEditingMessage restores the stashed draft', async () => {
        const draft = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'wip' }] }] }
        logic.actions.setDraftContent(draft)
        logic.actions.setDraftIsPrivate(false)
        logic.actions.startEditingMessage({
            id: 'note-1',
            content: 'note',
            richContent: { type: 'doc', content: [] },
            authorType: 'human',
            authorName: 'Me',
            createdAt: '2026-01-01T00:00:00Z',
            isPrivate: true,
        })
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.cancelEditingMessage()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.editingMessageId).toBeNull()
        expect(logic.values.draftContent).toEqual(draft)
        expect(logic.values.draftIsPrivate).toBe(false)
        expect(logic.values.stashedDraftContent).toBeNull()
    })

    test('sendMessage while editing hits the note update endpoint and restores the stashed draft', async () => {
        const draft = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'wip' }] }] }
        const updatedRich = {
            type: 'doc',
            content: [{ type: 'paragraph', content: [{ type: 'text', text: 'updated' }] }],
        }
        const commentsListMock = api.comments.list as jest.Mock
        commentsListMock.mockResolvedValue({
            results: [
                {
                    id: 'note-1',
                    content: 'updated',
                    rich_content: updatedRich,
                    version: 1,
                    created_at: '2026-01-01T00:00:00Z',
                    item_context: { author_type: 'support', is_private: true },
                    created_by: { id: 1, uuid: 'u1', distinct_id: 'd1', first_name: 'Me', email: 'me@posthog.com' },
                },
            ],
        })
        logic.actions.setMessages([
            {
                id: 'note-1',
                content: 'note',
                rich_content: { type: 'doc', content: [] },
                created_at: '2026-01-01T00:00:00Z',
                item_context: { author_type: 'support', is_private: true },
                created_by: { id: 1, uuid: 'u1', distinct_id: 'd1', first_name: 'Me', email: 'me@posthog.com' },
                version: 0,
            } as any,
        ])
        logic.actions.setDraftContent(draft)
        logic.actions.setDraftIsPrivate(false)
        logic.actions.startEditingMessage({
            id: 'note-1',
            content: 'note',
            richContent: { type: 'doc', content: [] },
            authorType: 'human',
            authorName: 'Me',
            createdAt: '2026-01-01T00:00:00Z',
            isPrivate: true,
        })
        await expectLogic(logic).toFinishAllListeners()

        const onSuccess = jest.fn()
        await expectLogic(logic, () => {
            logic.actions.sendMessage('updated', updatedRich, true, onSuccess)
        }).toFinishAllListeners()

        expect(noteUpdateMock).toHaveBeenCalledWith(expect.any(String), 'ticket-1', 'note-1', {
            message: 'updated',
            rich_content: updatedRich,
        })
        expect(createResponseMock).not.toHaveBeenCalled()
        expect(onSuccess).not.toHaveBeenCalled()
        expect(logic.values.editingMessageId).toBeNull()
        expect(logic.values.draftContent).toEqual(draft)
        expect(logic.values.draftIsPrivate).toBe(false)
        expect(logic.values.stashedDraftContent).toBeNull()
        const updated = logic.values.chatMessages.find((m) => m.id === 'note-1')
        expect(updated?.content).toBe('updated')
        expect(updated?.richContent).toEqual(updatedRich)
        expect(updated?.version).toBe(1)
    })

    test('setMessages aborts edit and restores the stashed draft when the note disappears', async () => {
        const draft = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'wip' }] }] }
        logic.actions.setDraftContent(draft)
        logic.actions.setDraftIsPrivate(false)
        logic.actions.startEditingMessage({
            id: 'note-1',
            content: 'note',
            richContent: { type: 'doc', content: [] },
            authorType: 'human',
            authorName: 'Me',
            createdAt: '2026-01-01T00:00:00Z',
            isPrivate: true,
        })
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setMessages([])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.editingMessageId).toBeNull()
        expect(logic.values.draftContent).toEqual(draft)
        expect(logic.values.draftIsPrivate).toBe(false)
    })

    test('switching notes while editing keeps the original stashed draft', async () => {
        const draft = { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'wip' }] }] }
        logic.actions.setDraftContent(draft)
        logic.actions.setDraftIsPrivate(false)
        logic.actions.startEditingMessage({
            id: 'note-1',
            content: 'note one',
            richContent: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'one' }] }] },
            authorType: 'human',
            authorName: 'Me',
            createdAt: '2026-01-01T00:00:00Z',
            isPrivate: true,
        })
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.startEditingMessage({
            id: 'note-2',
            content: 'note two',
            richContent: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'two' }] }] },
            authorType: 'human',
            authorName: 'Me',
            createdAt: '2026-01-01T00:00:00Z',
            isPrivate: true,
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.editingMessageId).toBe('note-2')
        expect(logic.values.stashedDraftContent).toEqual(draft)

        logic.actions.cancelEditingMessage()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.draftContent).toEqual(draft)
    })
})

describe('supportTicketSceneLogic sidePanelContext', () => {
    let logic: ReturnType<typeof supportTicketSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = supportTicketSceneLogic({ id: 'new' })
        logic.mount()
        logic.actions.setTicket(makeTicket())
    })

    // Access control and discussions are separate consumers of the same selector key. Defining
    // one selector per concern silently drops all but the last, so assert they coexist.
    it('exposes access control and discussion context together', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DISCUSSIONS_SLACK_SYNC]: true })

        expect(logic.values.sidePanelContext).toEqual({
            access_control_resource: 'ticket',
            access_control_resource_id: 'ticket-1',
            activity_scope: ActivityScope.TICKET,
            activity_item_id: 'ticket-1',
        })
    })

    it('keeps access control context when the discussions flag is off', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DISCUSSIONS_SLACK_SYNC]: false })

        expect(logic.values.sidePanelContext).toEqual({
            access_control_resource: 'ticket',
            access_control_resource_id: 'ticket-1',
        })
    })
})

describe('supportTicketSceneLogic discussion polling', () => {
    let logic: ReturnType<typeof supportTicketSceneLogic.build>
    const discussionProps = { scope: ActivityScope.TICKET, item_id: 'ticket-1' }

    beforeEach(() => {
        initKeaTests()
        logic = supportTicketSceneLogic({ id: 'new' })
        logic.mount()
        logic.actions.setTicket(makeTicket())
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DISCUSSIONS_SLACK_SYNC]: true })
    })

    afterEach(() => {
        stopPolling(logic)
    })

    // refreshComments, not loadComments: loadComments scrolls the side panel to the newest comment on
    // every success, so polling with it would move a reader off their place every 20 seconds.
    it('refreshes the ticket-scoped discussion without moving the reader', async () => {
        const discussion = commentsLogic(discussionProps)
        discussion.mount()
        const refreshComments = jest.spyOn(discussion.actions, 'refreshComments')
        const loadComments = jest.spyOn(discussion.actions, 'loadComments')

        logic.actions.pollDiscussionThread()
        await expectLogic(logic).toFinishAllListeners()

        expect(refreshComments).toHaveBeenCalledTimes(1)
        expect(loadComments).not.toHaveBeenCalled()

        refreshComments.mockRestore()
        loadComments.mockRestore()
        discussion.unmount()
    })

    // An edit or a completed task leaves the comment count untouched, so a count-based gate would
    // leave the card and the open panel showing text nobody has written for a while.
    it('refreshes even when no comment was added or removed', async () => {
        const discussion = commentsLogic(discussionProps)
        discussion.mount()
        const refreshComments = jest.spyOn(discussion.actions, 'refreshComments')

        logic.actions.pollDiscussionThread()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.pollDiscussionThread()
        await expectLogic(logic).toFinishAllListeners()

        expect(refreshComments).toHaveBeenCalledTimes(2)

        refreshComments.mockRestore()
        discussion.unmount()
    })

    it('does not refresh when the discussions flag is off', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DISCUSSIONS_SLACK_SYNC]: false })
        const discussion = commentsLogic(discussionProps)
        discussion.mount()
        const refreshComments = jest.spyOn(discussion.actions, 'refreshComments')

        logic.actions.pollDiscussionThread()
        await expectLogic(logic).toFinishAllListeners()

        expect(refreshComments).not.toHaveBeenCalled()

        refreshComments.mockRestore()
        discussion.unmount()
    })

    // findMounted is only a null guard. In the app the ticket page mounts this logic to render its
    // cards, so the poll does reach it on every open ticket; this covers the torn-down case only.
    it('does not throw when the discussion logic is not mounted', async () => {
        expect(commentsLogic.findMounted(discussionProps)).toBeNull()

        logic.actions.pollDiscussionThread()
        await expectLogic(logic).toFinishAllListeners()

        expect(commentsLogic.findMounted(discussionProps)).toBeNull()
    })
})
