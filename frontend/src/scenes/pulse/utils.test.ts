import { urls } from 'scenes/urls'

import { PulseFindingType } from './pulseTypes'
import {
    SENSITIVITY_PRESETS,
    buildFindingInsightContext,
    buildMaxSeedPrompt,
    describeAbsoluteChange,
    describeChange,
    describeReference,
    findingShortId,
    formatSignedNumber,
    formatSignedPct,
    suggestedNextStep,
} from './utils'

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

    it('formats signed numbers, abbreviating large values', () => {
        expect(formatSignedNumber(94)).toBe('+94')
        expect(formatSignedNumber(-61)).toBe('-61')
        expect(formatSignedNumber(0)).toBe('0') // a flat delta stays unsigned, not "+0"
        expect(formatSignedNumber(21_849_087_616)).toBe('+21.8B')
    })

    it('describes absolute change with human-readable numbers', () => {
        expect(describeAbsoluteChange(FINDING)).toBe('64 this week vs 125/wk typical (-61)')
        expect(
            describeAbsoluteChange({ ...FINDING, current_value: 43_106_067_556, baseline_value: 21_256_979_940 })
        ).toBe('43.1B this week vs 21.3B/wk typical (+21.8B)')
    })

    it('describes references as labelled deep links', () => {
        expect(describeReference({ type: 'feature_flag', label: 'new-onboarding', id: '7' })).toEqual({
            label: 'Flag: new-onboarding',
            to: '/feature_flags/7',
        })
        expect(describeReference({ type: 'experiment', label: 'checkout-v2', id: '3' })).toEqual({
            label: 'Experiment: checkout-v2',
            to: urls.experiment('3'),
        })
        // No id -> a label-only chip, no link.
        expect(describeReference({ type: 'feature_flag', label: 'mystery' })).toEqual({ label: 'Flag: mystery' })
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

    it('extracts the insight short id from the descriptor url, or null', () => {
        expect(findingShortId({ ...FINDING, metric_descriptor: { url: '/insights/abc123' } })).toBe('abc123')
        expect(findingShortId({ ...FINDING, metric_descriptor: { url: '/insights/abc123?foo=1' } })).toBe('abc123')
        expect(findingShortId({ ...FINDING, metric_descriptor: {} })).toBeNull()
        expect(findingShortId({ ...FINDING, metric_descriptor: { url: '/feature_flags/7' } })).toBeNull()
    })

    it('builds structured Max context only for insight-backed findings', () => {
        const insightFinding = {
            ...FINDING,
            metric_descriptor: { url: '/insights/abc123', query: { kind: 'TrendsQuery' } },
        }
        expect(buildFindingInsightContext(insightFinding)).toEqual({
            short_id: 'abc123',
            name: 'purchase_completed',
            query: { kind: 'TrendsQuery' },
        })
        // No short id (event-sourced) -> null, handoff degrades to prompt-only.
        expect(
            buildFindingInsightContext({ ...FINDING, metric_descriptor: { query: { kind: 'TrendsQuery' } } })
        ).toBeNull()
    })

    it('suggests diving into the segment when a finding is concentrated', () => {
        const step = suggestedNextStep(FINDING) // attribution_breakdown = $browser/Safari
        expect(step?.label).toBe('Dive into Safari')
        expect(step?.seed).toContain('purchase_completed')
        expect(step?.seed).toContain('Safari')
    })

    it('suggests checking a coincident experiment, then a flag, then nothing', () => {
        const base = { ...FINDING, attribution_breakdown: null }
        const withExperiment = {
            ...base,
            evidence: { references: [{ type: 'experiment', label: 'checkout-v2', id: '3' }] },
        }
        expect(suggestedNextStep(withExperiment)?.label).toBe('Check the checkout-v2 experiment')

        const withFlag = {
            ...base,
            evidence: { references: [{ type: 'feature_flag', label: 'new-onboarding', id: '7' }] },
        }
        expect(suggestedNextStep(withFlag)?.label).toBe('Check the new-onboarding flag')

        // No segment and no references -> no specific lead (generic "Ask Max why" covers it).
        expect(suggestedNextStep({ ...base, evidence: null })).toBeNull()
    })
})
