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

    it('offers the response target column to everyone', () => {
        expect(keysOf(all, context)).toContain('response_target')
        expect(keysOf(all, { aiEnabled: false, embedded: true })).toContain('response_target')
    })

    it('renders in canonical order regardless of selection order', () => {
        const shuffled: TicketColumnKey[] = ['updated_at', 'status', 'ticket_number', 'tags']
        expect(keysOf(shuffled, context)).toEqual(['ticket_number', 'status', 'tags', 'updated_at'])
    })

    it('labels the response target cell against the configured ladder', () => {
        const groups = [
            { label: 'VIPs', tags: ['vip'] },
            { label: 'Everyone else', tags: ['plan_free'] },
        ]
        const column = buildTicketColumns(['response_target'], { ...context, responseTargetGroups: groups }).find(
            (c): c is LemonTableColumn<Ticket, keyof Ticket | undefined> => 'key' in c && c.key === 'response_target'
        )
        const cell = column!.render!(undefined, { tags: ['plan_free'] } as unknown as Ticket, 0, 1)
        expect(JSON.stringify(cell)).toContain('Everyone else')
    })
})
