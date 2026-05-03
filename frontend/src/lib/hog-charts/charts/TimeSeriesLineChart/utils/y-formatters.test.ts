import { buildYTickFormatter } from './y-formatters'

const NBSP = ' '

describe('buildYTickFormatter', () => {
    it.each([
        ['numeric', { format: 'numeric' as const }, 1234, '1,234'],
        ['percentage', { format: 'percentage' as const }, 50, '50%'],
        ['percentage_scaled', { format: 'percentage_scaled' as const }, 0.5, '50%'],
        ['duration', { format: 'duration' as const }, 90, `1m${NBSP}30s`],
        ['duration_ms', { format: 'duration_ms' as const }, 1500, '1.5s'],
        ['short', { format: 'short' as const }, 1500, `1.5${NBSP}K`],
        ['prefix and suffix', { format: 'numeric' as const, prefix: '~', suffix: '!' }, 7, '~7!'],
        ['prefix preserved on negative', { format: 'numeric' as const, prefix: '$' }, -42, '$-42'],
    ])('%s', (_, config, value, expected) => {
        expect(buildYTickFormatter(config)(value)).toBe(expected)
    })

    it('formats currency with the supplied currency code', () => {
        const fmt = buildYTickFormatter({ format: 'currency', currency: 'USD' })
        expect(fmt(1234)).toMatch(/\$/)
        expect(fmt(1234)).toMatch(/1,?234/)
    })

    it.each([
        ['no currency code', undefined],
        ['invalid currency code', 'NOT-A-CURRENCY'],
    ])('falls back to human friendly currency with %s', (_, currency) => {
        const fmt = buildYTickFormatter({ format: 'currency', currency })
        expect(fmt(1234)).toMatch(/\d/)
    })

    it('respects decimalPlaces for numeric format', () => {
        const fmt = buildYTickFormatter({ format: 'numeric', decimalPlaces: 2 })
        expect(fmt(1.2345)).toBe('1.23')
    })
})
