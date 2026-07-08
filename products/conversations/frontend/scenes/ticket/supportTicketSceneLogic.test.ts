import type { Ticket } from '../../types'
import { EmailReplyBlockedReason, getEmailReplyBlockedReason } from './supportTicketSceneLogic'

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
