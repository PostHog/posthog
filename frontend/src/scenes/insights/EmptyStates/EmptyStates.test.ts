import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'

import { deriveEmptyStateHints } from './EmptyStates'

describe('deriveEmptyStateHints', () => {
    const baseQuery: TrendsQuery = {
        kind: NodeKind.TrendsQuery,
        series: [],
    }

    it('returns no hints for an empty query', () => {
        expect(deriveEmptyStateHints(baseQuery)).toEqual([])
    })

    it('returns no hints when query is missing', () => {
        expect(deriveEmptyStateHints(null)).toEqual([])
        expect(deriveEmptyStateHints(undefined)).toEqual([])
    })

    it('flags filterTestAccounts when explicitly true', () => {
        const hints = deriveEmptyStateHints({ ...baseQuery, filterTestAccounts: true })
        expect(hints).toHaveLength(1)
        expect(hints[0]).toMatch(/test accounts/i)
    })

    it('does not flag filterTestAccounts when false or unset', () => {
        expect(deriveEmptyStateHints({ ...baseQuery, filterTestAccounts: false })).toEqual([])
        expect(deriveEmptyStateHints(baseQuery)).toEqual([])
    })

    it('flags property filters when present as an array', () => {
        const hints = deriveEmptyStateHints({
            ...baseQuery,
            properties: [{ key: 'foo', value: 'bar', operator: 'exact', type: 'event' }] as any,
        })
        expect(hints.some((h) => /property filter/i.test(h))).toBe(true)
    })

    it('does not flag empty property arrays', () => {
        expect(deriveEmptyStateHints({ ...baseQuery, properties: [] })).toEqual([])
    })

    it('flags a narrow date range like -1d, -24h, -7d', () => {
        for (const dateFrom of ['-1d', '-24h', '-7d', '-1h']) {
            const hints = deriveEmptyStateHints({
                ...baseQuery,
                dateRange: { date_from: dateFrom },
            })
            expect(hints.some((h) => /date range/i.test(h))).toBe(true)
        }
    })

    it('does not flag wider date ranges like -30d or all-time', () => {
        for (const dateFrom of ['-30d', '-90d', 'all', undefined]) {
            const hints = deriveEmptyStateHints({
                ...baseQuery,
                dateRange: { date_from: dateFrom ?? null },
            })
            expect(hints.some((h) => /date range/i.test(h))).toBe(false)
        }
    })

    it('combines multiple hints when several heuristics match', () => {
        const hints = deriveEmptyStateHints({
            ...baseQuery,
            filterTestAccounts: true,
            properties: [{ key: 'a', value: '1', operator: 'exact', type: 'event' }] as any,
            dateRange: { date_from: '-1d' },
        })
        expect(hints).toHaveLength(3)
    })

    it('unwraps an InsightVizNode wrapper', () => {
        const wrapped = {
            kind: NodeKind.InsightVizNode,
            source: { ...baseQuery, filterTestAccounts: true },
        } as any
        const hints = deriveEmptyStateHints(wrapped)
        expect(hints.some((h) => /test accounts/i.test(h))).toBe(true)
    })
})
