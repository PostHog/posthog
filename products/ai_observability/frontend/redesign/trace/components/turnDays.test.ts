import { withTimezone } from '../../shared/testTimezone'
import { ConversationTurn } from '../types'
import { startsDay } from './turnDays'

function turnAt(timestamp: string): ConversationTurn {
    return {
        id: timestamp,
        timestamp,
        waitMs: null,
        error: null,
        input: { kind: 'messages', messages: [] },
        output: { kind: 'messages', messages: [] },
    }
}

describe('turnDays', () => {
    test.each([
        ['UTC', 'the first turn shown', null, '2026-09-01T10:00:00Z', true],
        ['UTC', 'a turn later the same day', '2026-09-01T00:00:00Z', '2026-09-01T23:59:59Z', false],
        ['UTC', 'a turn just after midnight', '2026-09-01T23:59:59Z', '2026-09-02T00:00:00Z', true],
        ['UTC', 'a turn days later', '2026-09-01T10:00:00Z', '2026-09-04T09:00:00Z', true],
        ['America/New_York', 'a turn after local midnight', '2026-09-02T03:00:00Z', '2026-09-02T05:00:00Z', true],
        ['America/New_York', 'a turn after UTC midnight', '2026-09-01T23:00:00Z', '2026-09-02T01:00:00Z', false],
        // Clocks go back on 1 November 2026, so that local day lasts 25 hours.
        ['America/New_York', 'a turn 24 hours later', '2026-11-01T04:30:00Z', '2026-11-02T04:30:00Z', false],
    ])('in %s, startsDay for %s', (timezone, _name, previous, timestamp, starts) => {
        withTimezone(timezone, () => {
            expect(startsDay(previous === null ? null : turnAt(previous), turnAt(timestamp))).toBe(starts)
        })
    })
})
