import { ticketStatusTagLabel } from './ticketStatusTagLabel'
import type { TicketStatus } from './types'

describe('ticketStatusTagLabel', () => {
    it.each<[TicketStatus | undefined, 'team' | 'customer', string | undefined]>([
        ['open', 'team', 'open'],
        ['on_hold', 'team', 'On hold'],
        ['on_hold', 'customer', 'On hold'],
        ['escalated', 'team', 'Escalated to Self-driving'],
        ['escalated', 'customer', 'Being investigated'],
        [undefined, 'customer', undefined],
    ])('labels %s for the %s audience as %s', (status, audience, expected) => {
        expect(ticketStatusTagLabel(status, audience)).toBe(expected)
    })
})
