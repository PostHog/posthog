import { buildYTickFormatter, type YAxisFormat } from './y-formatters'

const NBSP = ' '

describe('buildYTickFormatter', () => {
    it.each([
        ['numeric', { format: 'numeric' as const }, 1234, '1,234'],
        ['percentage', { format: 'percentage' as const }, 50, '50%'],
        ['percentage_scaled', { format: 'percentage_scaled' as const }, 0.5, '50%'],
        ['duration', { format: 'duration' as const }, 90, `1m${NBSP}30s`],
        ['duration_ms', { format: 'duration_ms' as const }, 1500, '1.5s'],
        ['duration_ns below one microsecond', { format: 'duration_ns' as const }, 500, '500ns'],
        ['duration_ns below one millisecond', { format: 'duration_ns' as const }, 500_000, '500µs'],
        ['duration_ns', { format: 'duration_ns' as const }, 1_500_000_000, '1.5s'],
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
        expect(fmt(0.012)).toBe('0.01')
    })

    const smallTickCases: { format: YAxisFormat; ticks: number[]; expected: string[] }[] = [
        {
            format: 'numeric',
            ticks: [0, -0.002, 0.002, 0.008, 0.01, 0.012],
            expected: ['0', '-0.002', '0.002', '0.008', '0.01', '0.012'],
        },
        { format: 'percentage', ticks: [0.005, 0.01], expected: ['0.005%', '0.01%'] },
        { format: 'percentage_scaled', ticks: [0.00005, 0.0001], expected: ['0.005%', '0.01%'] },
    ]

    it.each(smallTickCases)('keeps small $format ticks distinct', ({ format, ticks, expected }) => {
        const fmt = buildYTickFormatter({ format })
        expect(ticks.map((tick) => fmt(tick))).toEqual(expected)
    })

    // Adapters pass a nullable config field straight through, and null coerces to 0 in `Math.max`
    it('floors precision at two decimals when minDecimalPlaces is null', () => {
        const fmt = buildYTickFormatter({ format: 'numeric', minDecimalPlaces: null as unknown as number })
        expect(fmt(1.2345)).toBe('1.23')
    })
})
