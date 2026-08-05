import type { Ticket } from '../../types'
import { customerLabel, isSameCustomer } from './mergeTicketModalLogic'

function ticket(overrides: Partial<Ticket>): Ticket {
    return { id: 'x', ticket_number: 1, distinct_id: '', ...overrides } as Ticket
}

describe('mergeTicketModalLogic helpers', () => {
    // The cross-customer confirmation the user must acknowledge hinges on this precedence,
    // so a flipped comparison would silently merge across customers without warning.
    it.each([
        [
            'same person id wins over differing distinct_ids',
            { person: { id: 'p1' } as any, distinct_id: 'a' },
            { person: { id: 'p1' } as any, distinct_id: 'b' },
            true,
        ],
        ['different person id', { person: { id: 'p1' } as any }, { person: { id: 'p2' } as any }, false],
        ['falls back to distinct_id when persons missing', { distinct_id: 'a' }, { distinct_id: 'a' }, true],
        ['different distinct_id', { distinct_id: 'a' }, { distinct_id: 'b' }, false],
        ['falls back to email, case-insensitive', { email_from: 'A@x.com' }, { email_from: 'a@x.com' }, true],
        ['no shared identity is not the same customer', {}, {}, false],
    ])('%s', (_name, a, b, expected) => {
        expect(isSameCustomer(ticket(a as Partial<Ticket>), ticket(b as Partial<Ticket>))).toBe(expected)
    })

    it.each([
        ['prefers person name', { person: { name: 'Ada' } as any, email_from: 'a@x.com', distinct_id: 'd' }, 'Ada'],
        ['falls back to email', { email_from: 'a@x.com', distinct_id: 'd' }, 'a@x.com'],
        ['falls back to distinct_id', { distinct_id: 'd' }, 'd'],
        ['unknown when nothing identifies the customer', {}, 'Unknown customer'],
    ])('customerLabel %s', (_name, overrides, expected) => {
        expect(customerLabel(ticket(overrides as Partial<Ticket>))).toBe(expected)
    })
})
