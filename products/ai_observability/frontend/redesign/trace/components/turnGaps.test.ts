import { ConversationTurn } from '../types'
import { formatSilence, isSlowWait, silenceBefore } from './turnGaps'

function turnAt(timestamp: string, waitMs: number | null): ConversationTurn {
    return {
        id: timestamp,
        timestamp,
        waitMs,
        error: null,
        input: { kind: 'messages', messages: [] },
        output: { kind: 'messages', messages: [] },
    }
}

describe('turnGaps', () => {
    test.each([
        [9_999, false],
        [10_000, true],
        [null, false],
    ])('isSlowWait(%s) is %s', (waitMs, slow) => {
        expect(isSlowWait(waitMs)).toBe(slow)
    })

    describe('silenceBefore', () => {
        const previous = turnAt('2026-09-01T10:00:00Z', 20_000)

        test.each([
            ['no previous turn', null, '2026-09-01T10:30:00Z', null],
            ['under a minute after the answer', previous, '2026-09-01T10:01:19Z', null],
            ['a minute after the answer', previous, '2026-09-01T10:01:20Z', 60_000],
            ['long after the answer', previous, '2026-09-01T11:00:20Z', 3_600_000],
        ])('%s', (_name, prior, timestamp, expected) => {
            expect(silenceBefore(prior, turnAt(timestamp, 1_000))).toBe(expected)
        })

        test('measures from the previous start when its wait is unknown', () => {
            expect(silenceBefore(turnAt('2026-09-01T10:00:00Z', null), turnAt('2026-09-01T10:01:00Z', null))).toBe(
                60_000
            )
        })
    })

    test.each([
        [120_000, '2 min later'],
        [3_600_000, '1 h later'],
        [259_200_000, '3 d later'],
    ])('formatSilence(%s) is %s', (ms, text) => {
        expect(formatSilence(ms)).toBe(text)
    })
})
