import { PulseFindingType } from './pulseTypes'
import { SENSITIVITY_PRESETS, buildMaxSeedPrompt, describeChange, formatSignedPct } from './utils'

const FINDING: PulseFindingType = {
    id: 'f1',
    digest: 'd1',
    metric_label: 'purchase_completed',
    metric_descriptor: {},
    current_value: 64,
    baseline_value: 125,
    change_pct: -0.49,
    robust_z: 4.2,
    impact: 5.5,
    attribution_breakdown: { property: '$browser', value: 'Safari' },
    evidence: null,
    narrative: 'purchase_completed is down 49% this week.',
    chart_thumbnail_url: '',
    rank: 0,
    created_at: '2026-05-26T00:00:00Z',
}

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

    it('buildMaxSeedPrompt includes the metric, signed change, breakdown, and narrative', () => {
        const seed = buildMaxSeedPrompt(FINDING)
        expect(seed).toContain('purchase_completed')
        expect(seed).toContain('-49%')
        expect(seed).toContain('Safari')
        expect(seed).toContain('$browser')
        expect(seed).toContain('down 49%') // the narrative is echoed verbatim
    })

    it('buildMaxSeedPrompt omits the breakdown clause when there is no attribution', () => {
        const seed = buildMaxSeedPrompt({ ...FINDING, attribution_breakdown: null })
        expect(seed).not.toContain('concentrated')
        expect(seed).toContain('purchase_completed')
    })
})
