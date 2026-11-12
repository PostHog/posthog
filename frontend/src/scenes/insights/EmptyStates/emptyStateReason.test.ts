import { dayjs } from 'lib/dayjs'

import { NodeKind } from '~/queries/schema/schema-general'

import {
    emptyStateRange,
    emptyStateReason,
    explainableEvents,
    hasPropertyFilters,
    rangeReaching,
} from './emptyStateReason'

describe('emptyStateReason', () => {
    const rangeStart = dayjs('2026-10-01')
    const rangeEnd = dayjs('2026-10-31')

    test.each([
        ['never-sent', { a: null, b: null }, false],
        ['last-seen-before', { a: '2026-09-20T00:00:00Z', b: null }, true],
        ['last-seen-after', { a: '2026-11-05T00:00:00Z' }, true],
        ['filtered', { a: '2026-09-01T00:00:00Z', b: '2026-10-15T00:00:00Z' }, true],
        ['filtered', { a: '2026-11-05T00:00:00Z', b: '2026-10-15T00:00:00Z' }, true],
        ['unknown', { a: '2026-10-15T00:00:00Z' }, false],
    ])('%s', (kind, lastSeen, hasFilters) => {
        expect(emptyStateReason({ lastSeen, rangeStart, rangeEnd, hasFilters }).kind).toBe(kind)
    })

    test.each([
        ['2026-11-01', { dateFrom: '-30d', label: 'Show last 30 days' }],
        ['2026-02-11', { dateFrom: '-1y', label: 'Show past year' }],
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

    const event = (name: string): Record<string, unknown> => ({ kind: NodeKind.EventsNode, event: name })
    test.each([
        ['trends counts every series', NodeKind.TrendsQuery, [event('a'), event('b'), event('a')], ['a', 'b']],
        ['a funnel counts only its first step', NodeKind.FunnelsQuery, [event('a'), event('b')], ['a']],
        [
            'an action series cannot be explained',
            NodeKind.TrendsQuery,
            [event('a'), { kind: NodeKind.ActionsNode, id: 1 }],
            null,
        ],
        ['a name with a comma cannot be looked up', NodeKind.TrendsQuery, [event('checkout,success')], null],
    ])('explainableEvents: %s', (_, kind, series, expected) => {
        expect(explainableEvents({ kind, series } as any)).toEqual(expected)
    })

    test('emptyStateRange prefers the range the backend resolved', () => {
        const range = emptyStateRange(
            { date_from: '2026-11-03T00:00:00Z', date_to: '2026-11-10T23:59:59Z' },
            { date_from: null }
        )
        expect(range.rangeStart?.toISOString()).toBe('2026-11-03T00:00:00.000Z')
        expect(range.rangeEnd?.toISOString()).toBe('2026-11-10T23:59:59.000Z')
    })
})
