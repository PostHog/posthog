import { getRowExpansionKey } from './rowExpansion'

const columns = ['event', '*', 'timestamp']
const row = (uuid: string) => ({ result: ['$pageview', { uuid }, '2026-10-12'] })

describe('getRowExpansionKey', () => {
    it('keeps the same event expanded after reordering and does not expand its replacement', () => {
        const first = row('event-a')
        const second = row('event-b')
        const expanded = [getRowExpansionKey(second, 1, columns, true)]
        const isExpanded = (value: ReturnType<typeof row>, index: number): boolean =>
            expanded.includes(getRowExpansionKey(value, index, columns, true))

        expect([first, second].map(isExpanded)).toEqual([false, true])
        expect([second, first].map(isExpanded)).toEqual([true, false])
        expect([first, row('event-c')].map(isExpanded)).toEqual([false, false])
    })

    it('uses the same key to collapse an event after it moves', () => {
        const second = row('event-b')
        expect(getRowExpansionKey(second, 1, columns, true)).toBe(getRowExpansionKey(second, 0, columns, true))
    })

    it('supports object event rows', () => {
        expect(getRowExpansionKey({ result: { uuid: 'event-a' } }, 2, columns, true)).toBe('event-a')
    })

    it.each([undefined, null, '', '   ', 123])('falls back to the index for unusable uuid %p', (uuid) => {
        expect(getRowExpansionKey({ result: ['$pageview', { uuid }] }, 2, columns, true)).toBe(2)
    })

    it('keeps the index fallback for missing event data and non-event queries', () => {
        expect(getRowExpansionKey({}, 3, columns, true)).toBe(3)
        expect(getRowExpansionKey(row('event-a'), 3, ['event', 'timestamp'], true)).toBe(3)
        expect(getRowExpansionKey(row('event-a'), 3, columns, false)).toBe(3)
    })
})
