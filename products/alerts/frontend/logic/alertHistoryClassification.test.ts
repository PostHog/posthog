import { AlertState, DetectorType } from '~/queries/schema/schema-general'

import type { AlertCheck } from '../types'
import { checkWouldFireUnderCurrentConfiguration, getAlertHistoryScoreName, llmCheckWouldFire } from './alertLogic'

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
        // The backend suppresses a confident anomaly that names only older points.
        [
            'confident verdict that skipped the latest point',
            { verdict_is_anomaly: true, confidence: 0.9, latest_point_not_flagged: true },
            false,
        ],
        ['check without a stored verdict', { rationale: 'older check' }, null],
        ['check without metadata', null, null],
    ])('%s', (_name, metadata, expected) => {
        expect(llmCheckWouldFire(check(metadata), 0.7)).toBe(expected)
    })
})

describe('checkWouldFireUnderCurrentConfiguration', () => {
    const modelCheck = check({ verdict_is_anomaly: false, confidence: 0.2 })
    it.each<[string, AlertCheck, any, boolean | null | undefined]>([
        // A folded "no anomaly" score sits above a statistical threshold without being a fire.
        ['AI check under a statistical detector', modelCheck, { type: DetectorType.ZSCORE, threshold: 0.5 }, null],
        ['AI check under the AI detector', modelCheck, { type: DetectorType.LLM, threshold: 0.7 }, false],
        ['statistical check under a statistical detector', check(null), { type: DetectorType.ZSCORE }, undefined],
        ['statistical check under the AI detector', check(null), { type: DetectorType.LLM }, null],
    ])('%s', (_name, alertCheck, detectorConfig, expected) => {
        expect(checkWouldFireUnderCurrentConfiguration(alertCheck, detectorConfig)).toBe(expected)
    })
})

describe('getAlertHistoryScoreName', () => {
    const modelCheck = check({ verdict_is_anomaly: true, confidence: 0.8 })
    it.each<[string, AlertCheck[], string]>([
        ['AI checks', [modelCheck], 'Anomaly confidence'],
        ['mixed checks', [modelCheck, check(null)], 'Anomaly score'],
        ['statistical checks', [check(null)], 'Anomaly score'],
        ['threshold checks', [modelCheck, { ...check(null), anomaly_scores: null }], 'Anomaly score'],
    ])('%s', (_name, checks, expected) => {
        expect(getAlertHistoryScoreName(true, { detector_config: { type: DetectorType.LLM }, checks })).toBe(expected)
    })
})
