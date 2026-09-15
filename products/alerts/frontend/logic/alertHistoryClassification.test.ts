import { AlertState } from '~/queries/schema/schema-general'

import type { AlertCheck } from '../types'
import { llmCheckWouldFire } from './alertLogic'

function check(triggered_metadata: Record<string, unknown> | null): AlertCheck {
    return {
        id: 'check',
        created_at: '2026-09-01T00:00:00Z',
        calculated_value: 40,
        state: AlertState.NOT_FIRING,
        targets_notified: false,
        anomaly_scores: [0.8],
        triggered_metadata,
        deliveries: null,
    }
}

describe('llmCheckWouldFire', () => {
    it.each([
        // A low-confidence "no anomaly" stores a high score, but never fires.
        ['negative verdict, low confidence', { verdict_is_anomaly: false, confidence: 0.2 }, false],
        ['positive verdict at the threshold', { verdict_is_anomaly: true, confidence: 0.7 }, true],
        ['positive verdict below the threshold', { verdict_is_anomaly: true, confidence: 0.5 }, false],
        ['check without a stored verdict', { rationale: 'older check' }, null],
        ['check without metadata', null, null],
    ])('%s', (_name, metadata, expected) => {
        expect(llmCheckWouldFire(check(metadata), 0.7)).toBe(expected)
    })
})
