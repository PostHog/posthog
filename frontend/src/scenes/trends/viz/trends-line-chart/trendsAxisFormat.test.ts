import { buildYTickFormatter } from 'lib/hog-charts'
import { AggregationAxisFormat } from 'scenes/insights/aggregationAxisFormat'

import { CurrencyCode, TrendsFilter } from '~/queries/schema/schema-general'

import { buildTrendsYAxisConfig, trendsFilterToYFormatterConfig } from './trendsAxisFormat'

const NBSP = ' '

describe('trendsFilterToYFormatterConfig', () => {
    it.each<AggregationAxisFormat>([
        'numeric',
        'duration',
        'duration_ms',
        'percentage',
        'percentage_scaled',
        'currency',
        'short',
    ])('passes aggregationAxisFormat=%s through to format', (aggregationAxisFormat) => {
        expect(trendsFilterToYFormatterConfig({ aggregationAxisFormat }, false).format).toBe(aggregationAxisFormat)
    })

    it('maps aggregationAxis* fields onto the generic config', () => {
        const trendsFilter: TrendsFilter = {
            aggregationAxisFormat: 'duration',
            aggregationAxisPrefix: '~',
            aggregationAxisPostfix: '!',
            decimalPlaces: 2,
            minDecimalPlaces: 1,
        }
        expect(trendsFilterToYFormatterConfig(trendsFilter, false, 'USD' as CurrencyCode)).toEqual({
            format: 'duration',
            prefix: '~',
            suffix: '!',
            decimalPlaces: 2,
            minDecimalPlaces: 1,
            currency: 'USD',
        })
    })

    it.each<[string, TrendsFilter | null]>([
        ['empty filter', {}],
        ['null filter', null],
    ])('defaults format to numeric for %s', (_, trendsFilter) => {
        expect(trendsFilterToYFormatterConfig(trendsFilter, false)).toEqual({ format: 'numeric' })
    })

    it('returns a percentage config when isPercentStackView is true, ignoring the trends filter', () => {
        const trendsFilter: TrendsFilter = { aggregationAxisFormat: 'currency', aggregationAxisPrefix: '$' }
        expect(trendsFilterToYFormatterConfig(trendsFilter, true, 'USD' as CurrencyCode)).toEqual({
            format: 'percentage',
        })
    })
})

describe('trends y-tick formatter end-to-end', () => {
    it.each<[string, TrendsFilter, number, string]>([
        ['numeric', { aggregationAxisFormat: 'numeric' }, 1234, '1,234'],
        ['percentage', { aggregationAxisFormat: 'percentage' }, 50, '50%'],
        ['duration', { aggregationAxisFormat: 'duration' }, 90, `1m${NBSP}30s`],
        [
            'prefix + suffix',
            { aggregationAxisFormat: 'numeric', aggregationAxisPrefix: '~', aggregationAxisPostfix: '!' },
            7,
            '~7!',
        ],
    ])('formats %s through the trends → hog-charts pipeline', (_, trendsFilter, value, expected) => {
        const fmt = buildYTickFormatter(trendsFilterToYFormatterConfig(trendsFilter, false))
        expect(fmt(value)).toBe(expected)
    })

    it('formats percent-stack values regardless of the underlying trends filter', () => {
        const trendsFilter: TrendsFilter = { aggregationAxisFormat: 'currency' }
        const fmt = buildYTickFormatter(trendsFilterToYFormatterConfig(trendsFilter, true, 'USD' as CurrencyCode))
        expect(fmt(50)).toBe('50%')
    })
})

describe('buildTrendsYAxisConfig', () => {
    it.each([
        ['log10', 'log'],
        ['linear', 'linear'],
        ['auto', 'linear'],
        [undefined, 'linear'],
        [null, 'linear'],
    ] as const)('translates yAxisScaleType "%s" to scale "%s"', (input, expected) => {
        expect(buildTrendsYAxisConfig(null, false, undefined, { yAxisScaleType: input }).scale).toBe(expected)
    })

    it('passes showGrid through from extras', () => {
        expect(buildTrendsYAxisConfig(null, false, undefined, { showGrid: true }).showGrid).toBe(true)
        expect(buildTrendsYAxisConfig(null, false, undefined, {}).showGrid).toBeUndefined()
    })

    it('spreads the formatter config from trendsFilterToYFormatterConfig', () => {
        const trendsFilter: TrendsFilter = {
            aggregationAxisFormat: 'duration',
            aggregationAxisPrefix: '~',
            decimalPlaces: 2,
        }
        const cfg = buildTrendsYAxisConfig(trendsFilter, false, 'USD' as CurrencyCode)
        expect(cfg).toMatchObject({ format: 'duration', prefix: '~', decimalPlaces: 2, currency: 'USD' })
    })

    it('forces percentage format when isPercentStackView is true', () => {
        const trendsFilter: TrendsFilter = { aggregationAxisFormat: 'currency', aggregationAxisPrefix: '$' }
        expect(buildTrendsYAxisConfig(trendsFilter, true, 'USD' as CurrencyCode).format).toBe('percentage')
    })
})
