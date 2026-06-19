import {
    compactNumber,
    formatCurrency,
    hexToRGBA,
    humanFriendlyCurrency,
    humanFriendlyDuration,
    humanFriendlyNumber,
    percentage,
} from './format'

const NBSP = ' '

describe('format helpers', () => {
    describe('humanFriendlyNumber', () => {
        it.each([
            ['integer with thousands separator', 1234, undefined, undefined, '1,234'],
            ['decimal rounded to 2 by default', 1234.5678, undefined, undefined, '1,234.57'],
            ['custom maximumFractionDigits', 1234.5678, 4, undefined, '1,234.5678'],
            ['minimumFractionDigits forces trailing zeros', 5, 2, 2, '5.00'],
            ['negative numbers', -1234, undefined, undefined, '-1,234'],
            ['zero', 0, undefined, undefined, '0'],
            ['NaN maxFractionDigits falls back to default', 1.234, NaN, undefined, '1.23'],
            ['out-of-range maxFractionDigits falls back to default', 1.234, 200, undefined, '1.23'],
            ['negative maxFractionDigits falls back to default', 1.234, -1, undefined, '1.23'],
        ] as const)('%s', (_, value, maxDigits, minDigits, expected) => {
            expect(humanFriendlyNumber(value, maxDigits, minDigits)).toBe(expected)
        })
    })

    describe('humanFriendlyCurrency', () => {
        it.each([
            ['number input', 1234.5, undefined, '$1,234.50'],
            ['string input', '1234.5', undefined, '$1,234.50'],
            ['undefined falls back to 0', undefined, undefined, '$0.00'],
            ['empty string falls back to 0', '', undefined, '$0.00'],
            ['custom precision', 1234.5678, 4, '$1,234.5678'],
            ['precision 0', 1234.5, 0, '$1,235'],
            ['invalid precision falls back to 2', 1.5, 200, '$1.50'],
        ] as const)('%s', (_, value, precision, expected) => {
            expect(humanFriendlyCurrency(value, precision)).toBe(expected)
        })
    })

    describe('humanFriendlyDuration', () => {
        it.each([
            ['empty string', '', '', undefined],
            ['null', null, '', undefined],
            ['undefined', undefined, '', undefined],
            ['maxUnits 0 returns empty', 90, '', { maxUnits: 0 }],
            ['zero', 0, '0s', undefined],
            ['sub-second renders as ms', 0.5, '500ms', undefined],
            ['exact second', 1, '1s', undefined],
            ['mid-minute', 90, `1m${NBSP}30s`, undefined],
            ['exact hour', 3600, '1h', undefined],
            ['hour + minute + second', 3661, `1h${NBSP}1m${NBSP}1s`, undefined],
            ['exact day', 86400, '1d', undefined],
            ['day + hour', 90000, `1d${NBSP}1h`, undefined],
            ['days suppress minutes/seconds', 90061, `1d${NBSP}1h`, undefined],
            ['negative', -90, `-1m${NBSP}30s`, undefined],
            ['negative forwards options', -90, '-1m', { maxUnits: 1 }],
            ['secondsPrecision rounds to N significant figures', 12.5, '13s', { secondsPrecision: 2 }],
            ['secondsFixed rounds to N fixed decimals', 12.5, '12.5s', { secondsFixed: 1 }],
            ['maxUnits 1 caps output', 3661, '1h', { maxUnits: 1 }],
            ['maxUnits 2 caps output', 3661, `1h${NBSP}1m`, { maxUnits: 2 }],
            ['string input parsed as number', '90', `1m${NBSP}30s`, undefined],
        ] as const)('%s', (_, value, expected, options) => {
            expect(humanFriendlyDuration(value, options)).toBe(expected)
        })
    })

    describe('percentage', () => {
        it.each([
            ['basic fraction', 0.234, undefined, undefined, '23.4%'],
            ['integer', 0.5, undefined, undefined, '50%'],
            ['negative', -0.25, undefined, undefined, '-25%'],
            ['Infinity', Infinity, undefined, undefined, '∞%'],
            ['custom max digits', 0.123456, 4, undefined, '12.3456%'],
            ['fixedPrecision pads zeros', 0.5, 2, true, '50.00%'],
        ] as const)('%s', (_, value, maxDigits, fixed, expected) => {
            expect(percentage(value, maxDigits, fixed)).toBe(expected)
        })
    })

    describe('compactNumber', () => {
        it.each([
            ['null returns dash', null, '-'],
            ['under 1000', 999, '999'],
            ['thousands', 1500, `1.5${NBSP}K`],
            ['millions', 1_500_000, `1.5${NBSP}M`],
            ['billions', 2_500_000_000, `2.5${NBSP}B`],
            ['trillions', 3_500_000_000_000, `3.5${NBSP}T`],
            ['negative thousands', -1500, `-1.5${NBSP}K`],
            ['rounded to 3 sig figs', 12345, `12.3${NBSP}K`],
            ['zero', 0, '0'],
        ] as const)('%s', (_, value, expected) => {
            expect(compactNumber(value)).toBe(expected)
        })
    })

    describe('formatCurrency', () => {
        it.each([
            ['USD prefixes with $', 1234, 'USD', '$1,234.00'],
            ['always uses 2 fixed decimal places', 1.5, 'USD', '$1.50'],
            ['EUR is prefixed in en-US locale', 1234, 'EUR', '€1,234.00'],
            ['GBP is prefixed', 1234, 'GBP', '£1,234.00'],
        ])('%s', (_, amount, currency, expected) => {
            expect(formatCurrency(amount, currency)).toBe(expected)
        })

        it('throws for invalid currency code', () => {
            expect(() => formatCurrency(1234, 'NOT-A-CURRENCY')).toThrow()
        })
    })

    describe('hexToRGBA', () => {
        it.each([
            ['6-digit hex', '#FF0000', 1, 'rgba(255,0,0,1)'],
            ['without hash prefix', 'FF0000', 1, 'rgba(255,0,0,1)'],
            ['lowercase hex', '#aabbcc', 0.5, 'rgba(170,187,204,0.5)'],
            ['shorthand 3-digit hex', '#f00', 1, 'rgba(255,0,0,1)'],
            ['8-digit hex preserves explicit alpha override', '#FF000080', 0.25, 'rgba(255,0,0,0.25)'],
            ['default alpha is 1', '#000000', undefined, 'rgba(0,0,0,1)'],
            ['malformed hex (wrong length) returns black', '#zz', 1, 'rgba(0,0,0,1)'],
        ])('%s', (_, hex, alpha, expected) => {
            expect(hexToRGBA(hex, alpha)).toBe(expected)
        })
    })
})
