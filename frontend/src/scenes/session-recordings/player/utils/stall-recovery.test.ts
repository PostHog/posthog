import { RecordingSegment } from '~/types'

import { MAX_STALL_RECOVERY_ATTEMPTS, continuesStallBurst, resolveStallRecovery } from './stall-recovery'

describe('stall recovery', () => {
    const segment = (startTimestamp: number, endTimestamp: number): RecordingSegment =>
        ({
            startTimestamp,
            endTimestamp,
            kind: 'window',
            isActive: true,
            durationMs: endTimestamp - startTimestamp,
        }) as RecordingSegment

    it('escalates the skip so a blockage longer than one frame is cleared', () => {
        const skips = [0, 1, 2, 3, 4].map((attempt) => resolveStallRecovery(attempt, 16.67, 1000, []))
        expect(skips).toEqual([
            { kind: 'skip', skipMs: 250 },
            { kind: 'skip', skipMs: 500 },
            { kind: 'skip', skipMs: 1000 },
            { kind: 'skip', skipMs: 2000 },
            { kind: 'skip', skipMs: 4000 },
        ])
    })

    it('caps the skip when the inactivity skip speed already makes it large', () => {
        expect(resolveStallRecovery(4, 1500, 1000, [])).toEqual({ kind: 'skip', skipMs: 10_000 })
    })

    it('seeks to the next segment once the attempts run out', () => {
        const segments = [segment(0, 2000), segment(5000, 9000)]
        expect(resolveStallRecovery(MAX_STALL_RECOVERY_ATTEMPTS, 16.67, 1000, segments)).toEqual({
            kind: 'seekToSegment',
            timestamp: 5000,
        })
    })

    it('gives up when no later segment can be played', () => {
        expect(resolveStallRecovery(MAX_STALL_RECOVERY_ATTEMPTS, 16.67, 1000, [segment(0, 2000)])).toEqual({
            kind: 'giveUp',
        })
    })

    it.each([
        ['the first attempt of a run', null, 1000, false],
        ['attempts a few frames apart', 1000, 1200, true],
        ['a stall after the player played again', 1000, 9000, false],
    ])('tracks bursts: %s', (_name, lastAttemptAt, at, expected) => {
        expect(continuesStallBurst(lastAttemptAt as number | null, at as number)).toBe(expected)
    })
})
