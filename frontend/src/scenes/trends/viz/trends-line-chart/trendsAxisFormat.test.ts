import { CurrencyCode, TrendsFilter } from '~/queries/schema/schema-general'

import { trendsFilterToYFormatterConfig } from './trendsAxisFormat'

describe('trendsFilterToYFormatterConfig', () => {
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

    it('defaults format to numeric when aggregationAxisFormat is unset', () => {
        expect(trendsFilterToYFormatterConfig({}, false)).toEqual({
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

    it('handles a null trendsFilter without throwing', () => {
        expect(trendsFilterToYFormatterConfig(null, false)).toEqual({
            format: 'numeric',
            prefix: undefined,
            suffix: undefined,
            decimalPlaces: undefined,
            minDecimalPlaces: undefined,
            currency: undefined,
        })
    })
})
