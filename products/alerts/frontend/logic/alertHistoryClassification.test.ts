import { AlertState, DetectorType } from '~/queries/schema/schema-general'

import type { AlertCheck } from '../types'
import { checkWouldFireUnderCurrentConfiguration } from './alertLogic'

function check(triggered_metadata: Record<string, unknown> | null, state = AlertState.NOT_FIRING): AlertCheck {
    return {
        id: 'check',
        created_at: '2026-09-01T00:00:00Z',
        calculated_value: 40,
        state,
        targets_notified: false,
        anomaly_scores: [0.8],
        triggered_metadata,
        deliveries: null,
    }
}

describe('checkWouldFireUnderCurrentConfiguration', () => {
    const firedCheck = check({ detector_type: 'llm', kind: 'drop', rationale: 'Dropped.' }, AlertState.FIRING)
    // An older AI check carries a stored confidence score, but its own state still decides.
    const olderCheck = check({ verdict_is_anomaly: true, confidence: 0.9 })
    it.each<[string, AlertCheck, any, boolean | null | undefined]>([
        ['fired AI check under the AI detector', firedCheck, { type: DetectorType.LLM }, true],
        ['older AI check under the AI detector', olderCheck, { type: DetectorType.LLM }, false],
        ['AI check under a statistical detector', olderCheck, { type: DetectorType.ZSCORE, threshold: 0.5 }, null],
        ['statistical check under a statistical detector', check(null), { type: DetectorType.ZSCORE }, undefined],
        ['statistical check under the AI detector', check(null), { type: DetectorType.LLM }, null],
    ])('%s', (_name, alertCheck, detectorConfig, expected) => {
        expect(checkWouldFireUnderCurrentConfiguration(alertCheck, detectorConfig)).toBe(expected)
    })
})
