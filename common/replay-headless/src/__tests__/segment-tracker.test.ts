import type { RecordingSegment } from '@posthog/replay-shared'

import { publishSegments, createSegmentTracker, signalRecordingEnded } from '../segment-tracker'

const makeSegment = (
    overrides: Partial<RecordingSegment> & Pick<RecordingSegment, 'startTimestamp' | 'endTimestamp'>
): RecordingSegment => ({
    kind: 'window',
    durationMs: overrides.endTimestamp - overrides.startTimestamp,
    isActive: true,
    ...overrides,
})

describe('segment-tracker', () => {
    beforeEach(() => {
        delete window.__POSTHOG_INACTIVITY_PERIODS__
        delete window.__POSTHOG_SEGMENT_COUNTER__
        delete window.__POSTHOG_CURRENT_SEGMENT_START_TS__
        delete window.__POSTHOG_RECORDING_ENDED__
    })

    describe('publishSegments', () => {
        it('converts segments to inactivity periods on the window', () => {
            const segments: RecordingSegment[] = [
                makeSegment({ startTimestamp: 1000000, endTimestamp: 2000000, isActive: true }),
                makeSegment({ startTimestamp: 2000000, endTimestamp: 3000000, isActive: false, kind: 'gap' }),
                makeSegment({ startTimestamp: 3000000, endTimestamp: 5000000, isActive: true }),
            ]

            publishSegments(segments)

            expect(window.__POSTHOG_INACTIVITY_PERIODS__).toEqual([
                { ts_from_s: 1000, ts_to_s: 2000, active: true },
                { ts_from_s: 2000, ts_to_s: 3000, active: false },
                { ts_from_s: 3000, ts_to_s: 5000, active: true },
            ])
            expect(window.__POSTHOG_SEGMENT_COUNTER__).toBe(0)
        })
    })

    describe('createSegmentTracker', () => {
        it('increments counter when crossing segment boundaries', () => {
            const segments: RecordingSegment[] = [
                makeSegment({ startTimestamp: 1000, endTimestamp: 2000 }),
                makeSegment({ startTimestamp: 2001, endTimestamp: 3000, kind: 'gap', isActive: false }),
                makeSegment({ startTimestamp: 3001, endTimestamp: 5000 }),
            ]
            publishSegments(segments)
            const track = createSegmentTracker(segments)

            track(1500)
            expect(window.__POSTHOG_SEGMENT_COUNTER__).toBe(1)
            expect(window.__POSTHOG_CURRENT_SEGMENT_START_TS__).toBe(1)

            // same segment — no increment
            track(1800)
            expect(window.__POSTHOG_SEGMENT_COUNTER__).toBe(1)

            track(2500)
            expect(window.__POSTHOG_SEGMENT_COUNTER__).toBe(2)
            expect(window.__POSTHOG_CURRENT_SEGMENT_START_TS__).toBe(2.001)

            track(4000)
            expect(window.__POSTHOG_SEGMENT_COUNTER__).toBe(3)
            expect(window.__POSTHOG_CURRENT_SEGMENT_START_TS__).toBe(3.001)
        })

        it('does nothing for timestamps outside all segments', () => {
            const segments: RecordingSegment[] = [makeSegment({ startTimestamp: 1000, endTimestamp: 2000 })]
            publishSegments(segments)
            const track = createSegmentTracker(segments)

            track(500)
            expect(window.__POSTHOG_SEGMENT_COUNTER__).toBe(0)
        })
    })

    describe('signalRecordingEnded', () => {
        it('sets the ended flag', () => {
            expect(window.__POSTHOG_RECORDING_ENDED__).toBeUndefined()
            signalRecordingEnded()
            expect(window.__POSTHOG_RECORDING_ENDED__).toBe(true)
        })
    })
})
