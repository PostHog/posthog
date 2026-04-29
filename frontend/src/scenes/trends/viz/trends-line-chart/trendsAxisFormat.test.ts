import { CurrencyCode, TrendsFilter } from '~/queries/schema/schema-general'

import { buildTrendsYTickFormatter } from './trendsAxisFormat'

const NBSP = ' '

describe('buildTrendsYTickFormatter', () => {
    it.each([
        ['numeric format passes through', { aggregationAxisFormat: 'numeric' as const }, 1234, '1,234'],
        ['percentage format', { aggregationAxisFormat: 'percentage' as const }, 50, '50%'],
        ['percentage_scaled format', { aggregationAxisFormat: 'percentage_scaled' as const }, 0.5, '50%'],
        ['duration format', { aggregationAxisFormat: 'duration' as const }, 90, `1m${NBSP}30s`],
        ['duration_ms format', { aggregationAxisFormat: 'duration_ms' as const }, 1500, '1.5s'],
        ['short format', { aggregationAxisFormat: 'short' as const }, 1500, `1.5${NBSP}K`],
        [
            'aggregationAxisPrefix is honored',
            { aggregationAxisFormat: 'numeric' as const, aggregationAxisPrefix: '$' },
            42,
            '$42',
        ],
        [
            'aggregationAxisPostfix is honored',
            { aggregationAxisFormat: 'numeric' as const, aggregationAxisPostfix: ' req' },
            42,
            '42 req',
        ],
        [
            'prefix and postfix combine',
            {
                aggregationAxisFormat: 'numeric' as const,
                aggregationAxisPrefix: '~',
                aggregationAxisPostfix: '!',
            },
            7,
            '~7!',
        ],
    ])('%s', (_, trendsFilter, value, expected) => {
        const formatter = buildTrendsYTickFormatter(trendsFilter as TrendsFilter, false)
        expect(formatter(value)).toBe(expected)
    })

    it('formats currency with the supplied currency code', () => {
        const trendsFilter: TrendsFilter = { aggregationAxisFormat: 'currency' }
        const formatter = buildTrendsYTickFormatter(trendsFilter, false, 'USD' as CurrencyCode)
        expect(formatter(1234)).toMatch(/\$/)
        expect(formatter(1234)).toMatch(/1,?234/)
    })

    it('returns percent values when isPercentStackView=true regardless of axis format', () => {
        const trendsFilter: TrendsFilter = { aggregationAxisFormat: 'currency' }
        const formatter = buildTrendsYTickFormatter(trendsFilter, true, 'USD' as CurrencyCode)
        expect(formatter(50)).toBe('50%')
    })

    it('handles a null trendsFilter without throwing', () => {
        const formatter = buildTrendsYTickFormatter(null, false)
        expect(formatter(123)).toBe('123')
    })
})
