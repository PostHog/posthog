import { dayjs } from 'lib/dayjs'

import { emptyStateReason, hasPropertyFilters, rangeReaching } from './emptyStateReason'

describe('emptyStateReason', () => {
    const rangeStart = dayjs('2026-10-01')
    const rangeEnd = dayjs('2026-10-31')

    test.each([
        ['never-sent', { a: null, b: null }, false],
        ['last-seen-before', { a: '2026-09-20T00:00:00Z', b: null }, true],
        ['last-seen-after', { a: '2026-11-05T00:00:00Z' }, true],
        ['filtered', { a: '2026-09-01T00:00:00Z', b: '2026-10-15T00:00:00Z' }, true],
        ['unknown', { a: '2026-10-15T00:00:00Z' }, false],
    ])('%s', (kind, lastSeen, hasFilters) => {
        expect(emptyStateReason({ lastSeen, rangeStart, rangeEnd, hasFilters }).kind).toBe(kind)
    })

    test.each([
        ['2026-11-01', { dateFrom: '-30d', label: 'Show last 30 days' }],
        ['2024-06-15', { dateFrom: '2024-06-08', label: 'Show from 8 Jun 2024' }],
    ])('rangeReaching %s', (lastSeen, expected) => {
        expect(rangeReaching(dayjs(lastSeen), dayjs('2026-11-10'))).toEqual(expected)
    })

    const filter = { key: '$browser', type: 'event', value: ['Safari'], operator: 'exact' }
    test.each([
        ['a flat list', [filter], true],
        ['nested groups', { type: 'AND', values: [{ type: 'AND', values: [filter] }] }, true],
        ['empty nested groups', { type: 'AND', values: [{ type: 'AND', values: [] }] }, false],
        ['nothing', undefined, false],
    ])('hasPropertyFilters with %s', (_, properties, expected) => {
        expect(hasPropertyFilters(properties)).toBe(expected)
    })
})
