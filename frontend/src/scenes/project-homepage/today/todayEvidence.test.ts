import { signalDestination } from './todayEvidence'
import { signal } from './todayTestFixtures'

describe('todayEvidence', () => {
    test.each([
        [
            'a recording without a start time, to its replay at the finding',
            signal({
                source_product: 'replay_vision',
                recording: { session_id: 's1', start_at: null, offset: '01:48' },
            }),
            { kind: 'link', to: '/replay/s1?t=103', external: false, label: 'Play at 01:48' },
        ],
        [
            'a recording, just before the finding',
            signal({
                source_product: 'replay_vision',
                recording: { session_id: 's1', start_at: '2026-10-02T12:17:06Z', offset: '01:48' },
            }),
            { kind: 'recording', sessionId: 's1', startAt: Date.parse('2026-10-02T12:17:06Z'), offset: '01:48' },
        ],
        [
            'an alert investigation, to its notebook',
            signal({ source_product: 'analytics', extra: { notebook_short_id: 'nb1' } }),
            { kind: 'link', to: '/notebooks/nb1', external: false, label: 'Open investigation' },
        ],
        [
            'a finding with a link, to that link',
            signal({ link: { url: 'https://example.slack.com/archives/C1/p2', text: 'Open thread' } }),
            { kind: 'link', to: 'https://example.slack.com/archives/C1/p2', external: true, label: 'Open thread' },
        ],
        ['a finding without a link, to its own text', signal({}), { kind: 'read' }],
    ])('sends %s', (_, input, expected) => {
        expect(signalDestination(input)).toEqual(expected)
    })
})
