import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'

import { isAffectedByRelativeDayRangeChange } from './RelativeDayRangeNotice'

function trendsQuery(date_from?: string | null, date_to?: string | null): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [],
        dateRange: { date_from, date_to },
    }
}

describe('isAffectedByRelativeDayRangeChange', () => {
    it.each<[string, TrendsQuery | null, boolean]>([
        ['seven-day relative range', trendsQuery('-7d'), true],
        ['fourteen-day relative range', trendsQuery('-14d'), true],
        ['six-day relative range', trendsQuery('-6d'), true],
        ['relative hour range', trendsQuery('-24h'), false],
        ['relative week range', trendsQuery('-2w'), false],
        ['absolute range', trendsQuery('2026-08-10'), false],
        ['relative range with an explicit end', trendsQuery('-7d', '2026-08-24'), false],
        ['default range', trendsQuery(null), true],
        ['missing query', null, false],
    ])('%s -> %s', (_name, source, expected) => {
        expect(isAffectedByRelativeDayRangeChange(source)).toBe(expected)
    })
})
