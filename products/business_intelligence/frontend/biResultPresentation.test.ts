import { formatBIMeasure } from './biResultPresentation'

describe('BI measure formatting', () => {
    it.each([
        ['purchase', 'purchase'],
        ['', ''],
        [true, 'true'],
        [['view', 'purchase'], '["view","purchase"]'],
        [{ status: 'ready' }, '{"status":"ready"}'],
        [null, '—'],
        [undefined, '—'],
        [NaN, '—'],
    ])('preserves aggregate results: %j', (value, expected) => {
        expect(formatBIMeasure(value)).toBe(expected)
    })

    it.each([0.125, '0.125'])('retains numeric formatting for %j', (value) => {
        expect(formatBIMeasure(value, { formatting: { style: 'percent', decimalPlaces: 1 } })).toBe('12.5%')
    })
})
