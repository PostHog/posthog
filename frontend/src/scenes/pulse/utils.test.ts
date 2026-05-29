import { SENSITIVITY_PRESETS, describeChange, formatSignedPct } from './utils'

describe('pulse utils', () => {
    it('formats signed percent', () => {
        expect(formatSignedPct(0.42)).toBe('+42%')
        expect(formatSignedPct(-0.1)).toBe('-10%')
    })

    it.each([
        [0, { direction: 'flat' as const, tone: 'muted' as const, label: 'flat' }],
        [0.42, { direction: 'up' as const, tone: 'success' as const, label: '+42%' }],
        [-0.1, { direction: 'down' as const, tone: 'danger' as const, label: '-10%' }],
    ])('describeChange(%s)', (pct, expected) => {
        expect(describeChange(pct)).toEqual(expected)
    })

    it('maps sensitivity presets to thresholds', () => {
        expect(SENSITIVITY_PRESETS.conservative).toEqual({ min_change_pct: 0.4, robust_z_threshold: 3.5 })
        expect(SENSITIVITY_PRESETS.balanced).toEqual({ min_change_pct: 0.25, robust_z_threshold: 3.5 })
        expect(SENSITIVITY_PRESETS.sensitive).toEqual({ min_change_pct: 0.15, robust_z_threshold: 3.0 })
    })
})
