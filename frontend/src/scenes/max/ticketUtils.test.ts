import type { BillingType } from '~/types'

import { ThreadMessage } from './maxLogic'
import {
    appendTicketMetadata,
    canCreateSupportTicket,
    composeTicketBody,
    formatTicketConfirmationMessage,
    getTicketPromptData,
    getTicketSummaryData,
    isTicketCommand,
    isTicketConfirmationMessage,
} from './ticketUtils'

const human = (content: string): ThreadMessage => ({ type: 'human', content }) as unknown as ThreadMessage
const ai = (content: string): ThreadMessage => ({ type: 'ai', content }) as unknown as ThreadMessage

const SUMMARY = 'PostHog AI Support Ticket Summary:\n\nIssue: Session recordings are not appearing in the dashboard.'
const DENIAL =
    'The `/ticket` command is available for customers on paid plans or active trials. You can upgrade your plan in the billing settings, or ask the community at https://posthog.com/questions for help. If your issue is about billing, you can always contact our support team through the in-app help panel.'

describe('ticketUtils', () => {
    describe('getTicketSummaryData', () => {
        it('does not treat a near-miss like /tickets as a ticket command', () => {
            const thread = [
                human('How do I create an insight?'),
                ai('You can create an insight by...'),
                human('/tickets'),
                ai("/tickets isn't a recognized slash command. You might be looking for /ticket (singular)."),
            ]

            expect(getTicketSummaryData(thread, false)).toBeNull()
        })

        it('does not treat an eligibility denial as a ticket summary', () => {
            const thread = [
                human('How do I create an insight?'),
                ai('You can create an insight by...'),
                human('/ticket'),
                ai(DENIAL),
            ]

            expect(getTicketSummaryData(thread, false)).toBeNull()
        })

        it('returns the summary when the response after /ticket is a real summary', () => {
            const thread = [
                human('How do I create an insight?'),
                ai('You can create an insight by...'),
                human('/ticket'),
                ai(SUMMARY),
            ]

            expect(getTicketSummaryData(thread, false)).toEqual({ summary: SUMMARY, messageIndex: 3 })
        })
    })

    describe('getTicketPromptData', () => {
        const prompt = "I'll help you create a support ticket"

        it.each([
            ['plain command with text', '/ticket sync failed', 'sync failed'],
            ['leading whitespace still prefills the text', '  /ticket sync failed', 'sync failed'],
            ['bare command has no prefill', '/ticket', undefined],
        ])('%s', (_name, content, expectedInitialText) => {
            const thread = [human(content), ai(prompt)]
            expect(getTicketPromptData(thread, false)).toEqual({ needed: true, initialText: expectedInitialText })
        })
    })

    describe('formatTicketConfirmationMessage', () => {
        it('promises the response time the plan covers', () => {
            expect(formatTicketConfirmationMessage('4321', '48 hours')).toBe(
                "I've created a support ticket for you.\nYour ticket ID is #4321.\nOur support team aims to get back to you within 48 hours."
            )
        })

        it('promises no response time when the plan has none', () => {
            const message = formatTicketConfirmationMessage('4321', null)
            expect(message).toBe(
                "I've created a support ticket for you.\nYour ticket ID is #4321.\nOur support team will get back to you soon!"
            )
            expect(message).not.toContain('within')
        })

        it.each([
            ['with a response time', '48 hours'],
            ['without a response time', null],
        ])('stays detectable as a confirmation %s', (_name, responseTime) => {
            expect(isTicketConfirmationMessage(ai(formatTicketConfirmationMessage('4321', responseTime)))).toBe(true)
        })
    })

    describe('canCreateSupportTicket', () => {
        const billing = (partial: Partial<BillingType>): BillingType => partial as BillingType

        it.each([
            ['paid subscription', billing({ subscription_level: 'paid' }), false, true],
            ['custom subscription', billing({ subscription_level: 'custom' }), false, true],
            [
                'free with active boost trial',
                billing({
                    subscription_level: 'free',
                    trial: { status: 'active', target: 'boost' } as BillingType['trial'],
                }),
                false,
                true,
            ],
            [
                'free with active scale trial',
                billing({
                    subscription_level: 'free',
                    trial: { status: 'active', target: 'scale' } as BillingType['trial'],
                }),
                false,
                true,
            ],
            [
                'free with active enterprise trial',
                billing({
                    subscription_level: 'free',
                    trial: { status: 'active', target: 'enterprise' } as BillingType['trial'],
                }),
                false,
                true,
            ],
            [
                'free with expired trial',
                billing({
                    subscription_level: 'free',
                    trial: { status: 'expired', target: 'boost' } as BillingType['trial'],
                }),
                false,
                false,
            ],
            ['free without trial', billing({ subscription_level: 'free' }), false, false],
            ['free but organization is new', billing({ subscription_level: 'free' }), true, true],
            ['billing not loaded, organization not new', null, false, false],
            ['billing not loaded, organization new', null, true, true],
        ])('%s', (_name, billingValue, isOrgNew, expected) => {
            expect(canCreateSupportTicket(billingValue, isOrgNew)).toBe(expected)
        })
    })

    describe('isTicketCommand', () => {
        it.each([
            ['/ticket', true],
            ['/ticket my recordings are broken', true],
            ['  /ticket  ', true],
            ['/tickets', false],
            ['/feedback', false],
            ['tell me about /ticket', false],
        ])('%s', (content, expected) => {
            expect(isTicketCommand(content)).toBe(expected)
        })
    })

    describe('composeTicketBody', () => {
        it.each([
            [
                'note leads with summary attached',
                'It still repros in prod',
                SUMMARY,
                `It still repros in prod\n\n----\n${SUMMARY}`,
            ],
            ['summary alone when note is empty', '', SUMMARY, SUMMARY],
            ['summary alone when note is whitespace', '   ', SUMMARY, SUMMARY],
            ['note alone when no summary', 'Recordings are missing', undefined, 'Recordings are missing'],
            ['empty when neither note nor summary', '  ', undefined, ''],
        ])('%s', (_name, note, summary, expected) => {
            expect(composeTicketBody({ note, summary })).toBe(expected)
        })
    })

    describe('appendTicketMetadata', () => {
        const ids = { conversationId: 'conv-1', traceId: 'trace-1' }

        it('returns empty string for an empty body so metadata alone is never submitted', () => {
            expect(appendTicketMetadata('', ids)).toBe('')
            expect(appendTicketMetadata('   ', ids)).toBe('')
        })

        it('appends conversation and trace ids to a non-empty body', () => {
            expect(appendTicketMetadata('My issue', ids)).toBe(
                'My issue\n\n----\nConversation ID: conv-1\nTrace ID: trace-1'
            )
        })

        it('omits the trace line when there is no trace id', () => {
            expect(appendTicketMetadata('My issue', { conversationId: 'conv-1', traceId: null })).toBe(
                'My issue\n\n----\nConversation ID: conv-1'
            )
        })
    })
})
