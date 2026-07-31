import { LemonTableColumn } from '@posthog/lemon-ui'

import { Ticket } from '../../types'
import { TICKET_COLUMN_ORDER, TicketColumnKey, buildTicketColumns } from './ticketColumns'

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

    it('offers the ticket group column to everyone', () => {
        expect(keysOf(all, context)).toContain('ticket_group')
        expect(keysOf(all, { aiEnabled: false, embedded: true })).toContain('ticket_group')
    })

    it('renders in canonical order regardless of selection order', () => {
        const shuffled: TicketColumnKey[] = ['updated_at', 'status', 'ticket_number', 'tags']
        expect(keysOf(shuffled, context)).toEqual(['ticket_number', 'status', 'tags', 'updated_at'])
    })

    describe('ticket group cell', () => {
        const groups: { label: string; filters: any[] }[] = [
            { label: 'VIPs', filters: [{ type: 'ticket_tags', operator: 'any_of', value: ['vip'] }] },
            { label: 'Everyone else', filters: [{ type: 'sql', expression: 'message_count > 5' }] },
        ]
        const renderCell = (ticket: Partial<Ticket>): string => {
            const column = buildTicketColumns(['ticket_group'], { ...context, ticketGroups: groups }).find(
                (c): c is LemonTableColumn<Ticket, keyof Ticket | undefined> => 'key' in c && c.key === 'ticket_group'
            )
            return JSON.stringify(column!.render!(undefined, ticket as Ticket, 0, 1))
        }

        it('labels from the server-computed rank against the configured groups', () => {
            expect(renderCell({ ticket_group_rank: 1 })).toContain('Everyone else')
            expect(renderCell({ ticket_group_rank: 0 })).toContain('VIPs')
        })

        it('falls back to the first group when the rank is missing or out of range', () => {
            expect(renderCell({})).toContain('VIPs')
            expect(renderCell({ ticket_group_rank: 9 })).toContain('VIPs')
        })

        it('keeps the truncating cell with the full label on hover', () => {
            const cell = renderCell({ ticket_group_rank: 1 })
            expect(cell).toContain('max-w-36')
            expect(cell).toContain('truncate')
            expect(cell).toContain('"title":"Everyone else"')
        })
    })
})
