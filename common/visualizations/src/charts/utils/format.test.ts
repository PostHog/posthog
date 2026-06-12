import { formatValue } from './format'

describe('formatValue', () => {
    describe('number format', () => {
        it.each([
            { value: 0, expected: '0' },
            { value: 1234, expected: '1,234' },
            { value: 1234.567, expected: '1,234.57' },
            { value: -42, expected: '-42' },
            { value: 0.1 + 0.2, expected: '0.3' },
        ])('formats $value as $expected', ({ value, expected }) => {
            expect(formatValue(value, 'number')).toBe(expected)
        })

        it('respects decimalPlaces', () => {
            expect(formatValue(1234.5, 'number', { decimalPlaces: 0 })).toBe('1,235')
            expect(formatValue(1234.5, 'number', { decimalPlaces: 3 })).toBe('1,234.500')
        })

        it('defaults to number format when format is omitted', () => {
            expect(formatValue(1234)).toBe('1,234')
        })
    })

    describe('compact format', () => {
        it.each([
            { value: 0, expected: '0' },
            { value: 999, expected: '999' },
            { value: 1000, expected: '1.0K' },
            { value: 1500, expected: '1.5K' },
            { value: 1_000_000, expected: '1.0M' },
            { value: 2_500_000, expected: '2.5M' },
            { value: 1_000_000_000, expected: '1.0B' },
            { value: -1500, expected: '-1.5K' },
            { value: -2_500_000, expected: '-2.5M' },
        ])('formats $value as $expected', ({ value, expected }) => {
            expect(formatValue(value, 'compact')).toBe(expected)
        })

        it('respects decimalPlaces', () => {
            expect(formatValue(1234, 'compact', { decimalPlaces: 2 })).toBe('1.23K')
            expect(formatValue(1_500_000, 'compact', { decimalPlaces: 0 })).toBe('2M')
        })
    })

    describe('percent format', () => {
        it.each([
            { value: 0, expected: '0.0%' },
            { value: 0.5, expected: '50.0%' },
            { value: 1, expected: '100.0%' },
            { value: 0.123, expected: '12.3%' },
            { value: -0.05, expected: '-5.0%' },
        ])('formats $value as $expected', ({ value, expected }) => {
            expect(formatValue(value, 'percent')).toBe(expected)
        })

        it('respects decimalPlaces', () => {
            expect(formatValue(0.12345, 'percent', { decimalPlaces: 2 })).toBe('12.35%')
            expect(formatValue(0.5, 'percent', { decimalPlaces: 0 })).toBe('50%')
        })
    })

    describe('duration format', () => {
        it.each([
            { value: 0, expected: '0.0s' },
            { value: 30, expected: '30.0s' },
            { value: 59.9, expected: '59.9s' },
            { value: 60, expected: '1m 0s' },
            { value: 90, expected: '1m 30s' },
            { value: 3600, expected: '1h 0m' },
            { value: 5400, expected: '1h 30m' },
            { value: 86400, expected: '1d 0h' },
            { value: 90000, expected: '1d 1h' },
            { value: -90, expected: '-1m 30s' },
        ])('formats $value seconds as $expected', ({ value, expected }) => {
            expect(formatValue(value, 'duration')).toBe(expected)
        })
    })

    describe('duration_ms format', () => {
        it('converts milliseconds to seconds before formatting', () => {
            expect(formatValue(30000, 'duration_ms')).toBe('30.0s')
            expect(formatValue(90000, 'duration_ms')).toBe('1m 30s')
        })
    })

    describe('none format', () => {
        it('returns the raw value as a string', () => {
            expect(formatValue(1234.567, 'none')).toBe('1234.567')
        })
    })

    describe('prefix and suffix', () => {
        it('prepends prefix', () => {
            expect(formatValue(1234, 'number', { prefix: '$' })).toBe('$1,234')
        })

        it('appends suffix', () => {
            expect(formatValue(1234, 'number', { suffix: ' USD' })).toBe('1,234 USD')
        })

        it('applies both', () => {
            expect(formatValue(42, 'number', { prefix: '~', suffix: ' items' })).toBe('~42 items')
        })
    })
})
