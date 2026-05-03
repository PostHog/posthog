import { AggregationAxisFormat } from 'scenes/insights/aggregationAxisFormat'

import { CurrencyCode, TrendsFilter } from '~/queries/schema/schema-general'

import { trendsFilterToYFormatterConfig } from './trendsAxisFormat'

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
        expect(trendsFilterToYFormatterConfig(trendsFilter, false)).toEqual({
            format: 'numeric',
            prefix: undefined,
            suffix: undefined,
            decimalPlaces: undefined,
            minDecimalPlaces: undefined,
            currency: undefined,
        })
    })

    it('returns a percentage config when isPercentStackView is true, ignoring the trends filter', () => {
        const trendsFilter: TrendsFilter = { aggregationAxisFormat: 'currency', aggregationAxisPrefix: '$' }
        expect(trendsFilterToYFormatterConfig(trendsFilter, true, 'USD' as CurrencyCode)).toEqual({
            format: 'percentage',
        })
    })
})
