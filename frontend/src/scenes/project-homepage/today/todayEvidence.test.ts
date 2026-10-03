import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import { pickEvidence, signalDestination } from './todayEvidence'
import { signal } from './todayTestFixtures'

describe('todayEvidence', () => {
    test.each([
        [
            'replay vision seconds',
            { session_id: 's1', start_time: 108, recording_start_time: '2026-10-02T12:15:23Z' },
            { startAt: Date.parse('2026-10-02T12:17:06Z'), offset: '01:48' },
        ],
        [
            'session replay offset text',
            { session_id: 's1', start_time: '02:05', session_start_time: '2026-10-02T12:00:00Z' },
            { startAt: Date.parse('2026-10-02T12:02:00Z'), offset: '02:05' },
        ],
    ])('opens a recording just before the finding from %s', (_, extra, expected) => {
        expect(
            signalDestination(
                signal({ source_product: 'replay_vision', extra: extra as unknown as SignalNodeApi['extra'] })
            )
        ).toEqual({ kind: 'recording', sessionId: 's1', ...expected })
    })

    test.each([
        [
            'an alert investigation',
            signal({
                source_product: 'analytics',
                source_type: 'anomaly_investigation',
                extra: { notebook_short_id: 'nb1' } as unknown as SignalNodeApi['extra'],
            }),
            { kind: 'link', to: '/notebooks/nb1', external: false, label: 'Open investigation' },
        ],
        [
            'a github issue',
            signal({
                source_product: 'github',
                source_type: 'issue',
                extra: { html_url: 'https://github.com/example/web/issues/7' } as unknown as SignalNodeApi['extra'],
            }),
            { kind: 'link', to: 'https://github.com/example/web/issues/7', external: true, label: 'Open issue' },
        ],
        [
            'a scout finding with a thread',
            signal({ content: 'A teammate reported it. Slack thread: https://example.slack.com/archives/C1/p2' }),
            { kind: 'link', to: 'https://example.slack.com/archives/C1/p2', external: true, label: 'Open thread' },
        ],
        [
            'a scout finding with only prose',
            signal({ content: 'A long finding without any link.'.repeat(10) }),
            { kind: 'read' },
        ],
    ])('sends %s to its source', (_, input, expected) => {
        expect(signalDestination(input)).toEqual(expected)
    })

    test('shows the newest signal from each source first', () => {
        const signals = [
            signal({ signal_id: 'old-replay', source_product: 'replay_vision', timestamp: '2026-09-01T00:00:00Z' }),
            signal({ signal_id: 'new-replay', source_product: 'replay_vision', timestamp: '2026-09-03T00:00:00Z' }),
            signal({ signal_id: 'scout', source_product: 'signals_scout', timestamp: '2026-08-01T00:00:00Z' }),
        ]
        expect(pickEvidence(signals, 2).map((picked) => picked.signal_id)).toEqual(['new-replay', 'scout'])
    })

    test('shows one row for several checks of the same alert', () => {
        const check = (id: string, timestamp: string): SignalNodeApi =>
            signal({
                signal_id: id,
                source_product: 'analytics',
                source_id: id,
                timestamp,
                extra: { alert_id: 'orders-alert' } as unknown as SignalNodeApi['extra'],
            })
        const signals = [check('early-check', '2026-09-01T09:00:00Z'), check('late-check', '2026-09-01T09:40:00Z')]
        expect(pickEvidence(signals, 3).map((picked) => picked.signal_id)).toEqual(['late-check'])
    })
})
