import type { RelatedOpenTicket, TicketRelatedOpen } from '../../types'
import { TICKET_COLUMN_ORDER, TicketColumnKey, buildTicketColumns, relatedOpenTooltip } from './ticketColumns'

const keysOf = (visible: TicketColumnKey[], context: { aiEnabled: boolean; embedded: boolean }): string[] =>
    buildTicketColumns(visible, context).map((column) => ('key' in column ? String(column.key) : ''))

describe('buildTicketColumns', () => {
    const all = TICKET_COLUMN_ORDER
    const context = { aiEnabled: true, embedded: false }

    it.each([
        ['hides a deselected column', ['ticket_number', 'status'], 'tags', false],
        ['keeps a selected column', ['ticket_number', 'tags'], 'tags', true],
        ['keeps the mandatory column even when deselected', ['tags'], 'ticket_number', true],
    ])('%s', (_name, visible, key, expected) => {
        expect(keysOf(visible as TicketColumnKey[], context).includes(key)).toBe(expected)
    })

    it.each([
        ['ai_triage', { aiEnabled: false, embedded: false }, 'ai_triage'],
        ['customer', { aiEnabled: true, embedded: true }, 'customer'],
    ])('never renders %s when the context excludes it', (_name, ctx, key) => {
        expect(keysOf(all, ctx)).not.toContain(key)
    })

    it('renders in canonical order regardless of selection order', () => {
        const shuffled: TicketColumnKey[] = ['updated_at', 'status', 'ticket_number', 'tags']
        expect(keysOf(shuffled, context)).toEqual(['ticket_number', 'status', 'tags', 'updated_at'])
    })
})

describe('relatedOpenTooltip', () => {
    const ticket = (overrides: Partial<RelatedOpenTicket> = {}): RelatedOpenTicket =>
        ({
            id: 'id',
            ticket_number: 101,
            status: 'open',
            email_subject: 'Cannot log in',
            last_message_text: null,
            ...overrides,
        }) as RelatedOpenTicket

    it('lists each ticket with its status and breaks the overflow down by status', () => {
        expect(
            relatedOpenTooltip({
                count: 6,
                counts_by_status: { open: 1, pending: 3, on_hold: 2 },
                tickets: [
                    ticket({ ticket_number: 101, status: 'open' }),
                    ticket({ ticket_number: 102, status: 'pending', email_subject: 'Billing' }),
                ],
            } as TicketRelatedOpen)
        ).toBe(
            [
                '#101 (open) Cannot log in',
                '#102 (pending) Billing',
                '+ 2 more pending tickets',
                '+ 2 more on hold tickets',
            ].join('\n')
        )
    })

    it('uses the singular for a single remaining ticket', () => {
        expect(
            relatedOpenTooltip({
                count: 2,
                counts_by_status: { on_hold: 2 },
                tickets: [ticket({ status: 'on_hold' })],
            } as TicketRelatedOpen)
        ).toBe(['#101 (on hold) Cannot log in', '+ 1 more on hold ticket'].join('\n'))
    })

    it.each([
        ['falls back to the last message when there is no subject', null, '**Bold**  text', '#101 (open) Bold text'],
        ['says so when there is neither', null, null, '#101 (open) No subject'],
        ['prefers the subject', 'Login help', 'Some message', '#101 (open) Login help'],
    ])('%s', (_name, email_subject, last_message_text, expected) => {
        expect(
            relatedOpenTooltip({
                count: 1,
                counts_by_status: { open: 1 },
                tickets: [ticket({ email_subject, last_message_text })],
            } as TicketRelatedOpen)
        ).toBe(expected)
    })
})
