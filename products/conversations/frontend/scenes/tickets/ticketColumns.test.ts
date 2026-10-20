import { ticketListAiTriage } from '../../types'
import { TICKET_COLUMN_ORDER, TicketColumnKey, buildTicketColumns } from './ticketColumns'

const keysOf = (visible: TicketColumnKey[], context: { aiEnabled: boolean; embedded: boolean }): string[] =>
    buildTicketColumns(visible, context).map((column) => ('key' in column ? String(column.key) : ''))

describe('ticket columns', () => {
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

    describe('ticketListAiTriage', () => {
        it('shows awaiting clarification instead of the clarified result', () => {
            expect(
                ticketListAiTriage({
                    status: 'awaiting_clarification',
                    result: 'clarified',
                })
            ).toEqual({
                kind: 'tag',
                label: 'Waiting for the customer',
                tagType: 'warning',
            })
        })

        it('keeps the suggested-reply result when the run is done', () => {
            expect(ticketListAiTriage({ status: 'done', result: 'suggested' })).toEqual({
                kind: 'tag',
                label: 'Suggested reply',
                tagType: 'warning',
            })
        })
    })
})
