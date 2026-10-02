import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import { signalDestination, signalHeadline, todayReportSections } from './todayReportPresentation'

function signal(overrides: Partial<SignalNodeApi>): SignalNodeApi {
    return {
        signal_id: 'signal-1',
        content: '',
        source_product: 'signals_scout',
        source_type: 'cross_source_issue',
        source_id: 'source-1',
        weight: 1,
        timestamp: '2026-10-01T10:00:00Z',
        extra: {} as SignalNodeApi['extra'],
        ...overrides,
    }
}

describe('todayReportPresentation', () => {
    test.each([
        [
            'markdown headings',
            'Lead sentence.\n\n## Problem\n\nBroken.\n\n## Solution\n\nFix the key.\n\n## Expected impact\n\nZero errors.',
            { lead: 'Lead sentence.', proposal: 'Fix the key.', expected: 'Zero errors.' },
        ],
        [
            'bold paragraph headings',
            'Lead sentence.\n\n**Evidence**\n\n- A finding.\n\n**Recommended next step**\n\n- Inspect the [rate](chart:rate) path.',
            { lead: 'Lead sentence.', proposal: '- Inspect the rate path.', expected: null },
        ],
        [
            'no headings',
            'Only a lead.\n\nA second paragraph.',
            { lead: 'Only a lead.', proposal: null, expected: null },
        ],
    ])('splits a summary with %s', (_, summary, expected) => {
        expect(todayReportSections(summary)).toEqual(expected)
    })

    test.each([
        [
            'replay vision seconds',
            { session_id: 's1', start_time: 108, recording_start_time: '2026-10-02T12:15:23Z' },
            { timestamp: Date.parse('2026-10-02T12:17:11Z'), offset: '01:48' },
        ],
        [
            'session replay offset text',
            { session_id: 's1', start_time: '02:05', session_start_time: '2026-10-02T12:00:00Z' },
            { timestamp: Date.parse('2026-10-02T12:02:05Z'), offset: '02:05' },
        ],
    ])('opens a recording at the finding from %s', (_, extra, expected) => {
        expect(
            signalDestination(
                signal({ source_product: 'replay_vision', extra: extra as unknown as SignalNodeApi['extra'] })
            )
        ).toEqual({ kind: 'recording', sessionId: 's1', ...expected })
    })

    test.each([
        [
            'an error tracking issue',
            'New error tracking issue created - this particular exception was observed for the first time:\nKeyError: `breakdown_value`\n\n```\nstack\n```',
            'KeyError: breakdown_value',
        ],
        [
            'a support ticket',
            'C: Three daily alerts fail with Decimal overflow\\. They monitor purchases.',
            'Three daily alerts fail with Decimal overflow.',
        ],
        [
            'long scout prose',
            'The export action declares no required scopes for this endpoint. Nearby tests already mint read keys.',
            'The export action declares no required scopes for this endpoint.',
        ],
    ])('writes a headline for %s', (_, content, expected) => {
        expect(signalHeadline(signal({ content }))).toEqual(expected)
    })
})
