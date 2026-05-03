import { buildYTickFormatter } from './y-formatters'

const NBSP = ' '

describe('buildYTickFormatter', () => {
    it.each([
        ['numeric default', {}, 1234, '1,234'],
        ['numeric explicit', { format: 'numeric' as const }, 1234, '1,234'],
        ['numeric zero', { format: 'numeric' as const }, 0, '0'],
        ['numeric negative', { format: 'numeric' as const }, -1234, '-1,234'],
        ['numeric very large', { format: 'numeric' as const }, 1_234_567_890, '1,234,567,890'],
        ['percentage', { format: 'percentage' as const }, 50, '50%'],
        ['percentage_scaled', { format: 'percentage_scaled' as const }, 0.5, '50%'],
        ['percentage zero', { format: 'percentage' as const }, 0, '0%'],
        ['duration', { format: 'duration' as const }, 90, `1m${NBSP}30s`],
        ['duration_ms', { format: 'duration_ms' as const }, 1500, '1.5s'],
        ['short', { format: 'short' as const }, 1500, `1.5${NBSP}K`],
        ['prefix', { format: 'numeric' as const, prefix: '$' }, 42, '$42'],
        ['suffix', { format: 'numeric' as const, suffix: ' req' }, 42, '42 req'],
        ['prefix and suffix', { format: 'numeric' as const, prefix: '~', suffix: '!' }, 7, '~7!'],
        ['prefix on negative', { format: 'numeric' as const, prefix: '$' }, -42, '$-42'],
    ])('%s', (_, config, value, expected) => {
        expect(buildYTickFormatter(config)(value)).toBe(expected)
    })

    it('formats currency with the supplied currency code', () => {
        const fmt = buildYTickFormatter({ format: 'currency', currency: 'USD' })
        expect(fmt(1234)).toMatch(/\$/)
        expect(fmt(1234)).toMatch(/1,?234/)
    })

    it('falls back to human friendly currency without a currency code', () => {
        const fmt = buildYTickFormatter({ format: 'currency' })
        expect(typeof fmt(1234)).toBe('string')
        expect(fmt(1234).length).toBeGreaterThan(0)
    })

    it('falls back to human friendly currency on invalid currency code', () => {
        const fmt = buildYTickFormatter({ format: 'currency', currency: 'NOT-A-CURRENCY' })
        expect(typeof fmt(1234)).toBe('string')
        expect(fmt(1234).length).toBeGreaterThan(0)
    })

    it('respects decimalPlaces for numeric format', () => {
        const fmt = buildYTickFormatter({ format: 'numeric', decimalPlaces: 2 })
        expect(fmt(1.2345)).toBe('1.23')
    })
})
