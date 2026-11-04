import { RRWebEvent } from '~/types'

import { RRWebEventSource, RRWebEventType } from './rrweb-types'
import { SegmentationEvent, activeMillisecondsFromSegmentationEvents, toSegmentationEvent } from './segmentation'

describe('segmentation', () => {
    describe('activeMillisecondsFromSegmentationEvents', () => {
        it('should return 0 for empty events array', () => {
            expect(activeMillisecondsFromSegmentationEvents([])).toBe(0)
        })

        it('should return 0 when there are no active events', () => {
            const segmentationEvents: SegmentationEvent[] = [
                { timestamp: 1000, isActive: false },
                { timestamp: 2000, isActive: false },
            ]

            expect(activeMillisecondsFromSegmentationEvents(segmentationEvents)).toBe(0)
        })

        it('should calculate active time for a single active event', () => {
            const segmentationEvents: SegmentationEvent[] = [{ timestamp: 1000, isActive: true }]

            // This is a special case where we count duration of active segments with one event as 1ms
            expect(activeMillisecondsFromSegmentationEvents(segmentationEvents)).toBe(1)
        })

        it('should calculate active time for consecutive active events', () => {
            const segmentationEvents: SegmentationEvent[] = [
                { timestamp: 1000, isActive: true },
                { timestamp: 2000, isActive: true },
                { timestamp: 3000, isActive: true },
            ]

            // Active time should be the difference between the first and last active event
            expect(activeMillisecondsFromSegmentationEvents(segmentationEvents)).toBe(2000)
        })

        it('should handle inactive periods between active events', () => {
            const segmentationEvents: SegmentationEvent[] = [
                { timestamp: 1000, isActive: true },
                { timestamp: 2100, isActive: false },
                { timestamp: 6001, isActive: true }, // 5 seconds after the last active event (exceeds activity threshold)
                { timestamp: 7001, isActive: true }, // 1 second after previous active event
            ]

            // Should create two separate active segments: 1100ms for the first and 1000ms for the second
            expect(activeMillisecondsFromSegmentationEvents(segmentationEvents)).toBe(2100)
        })

        it('should handle events that are not in chronological order', () => {
            const segmentationEvents: SegmentationEvent[] = [
                { timestamp: 3000, isActive: true },
                { timestamp: 1000, isActive: true }, // Out of order
                { timestamp: 2000, isActive: true },
            ]

            // Events should be sorted and active time calculated correctly
            expect(activeMillisecondsFromSegmentationEvents(segmentationEvents)).toBe(2000)
        })

        it('should handle mixed active and inactive events', () => {
            const segmentationEvents: SegmentationEvent[] = [
                { timestamp: 500, isActive: false },
                { timestamp: 1000, isActive: true },
                { timestamp: 1500, isActive: false },
                { timestamp: 2000, isActive: true },
                { timestamp: 2500, isActive: false },
                { timestamp: 3000, isActive: true },
            ]

            // Active time should be the difference between the first and last active event
            expect(activeMillisecondsFromSegmentationEvents(segmentationEvents)).toBe(2000)
        })

        it('should maintain one segment when inactive events are within activity threshold', () => {
            const segmentationEvents: SegmentationEvent[] = [
                // First active event
                { timestamp: 1000, isActive: true },
                // Inactive events at 1-second intervals
                { timestamp: 2000, isActive: false }, // 1 second after first event
                { timestamp: 3000, isActive: false }, // 2 seconds after first event
                { timestamp: 4000, isActive: false }, // 3 seconds after first event
                { timestamp: 5000, isActive: false }, // 4 seconds after first event
                { timestamp: 6000, isActive: false }, // 5 seconds after first event
                // After the activity threshold (5 seconds since the last active event)
                { timestamp: 6001, isActive: false },
            ]

            // Should create one active segment with duration of 5000ms (from 1000 to 6000)
            expect(activeMillisecondsFromSegmentationEvents(segmentationEvents)).toBe(5000)
        })

        it('should return an integer when timestamps are fractional', () => {
            const segmentationEvents: SegmentationEvent[] = [
                { timestamp: 1000.25, isActive: true },
                { timestamp: 2000.75, isActive: true },
                { timestamp: 3000.5, isActive: true },
            ]

            const result = activeMillisecondsFromSegmentationEvents(segmentationEvents)
            // Result should be an integer, not 2000.25
            expect(Number.isInteger(result)).toBe(true)
            expect(result).toBe(2000)
        })
    })

    describe('toSegmentationEvent', () => {
        it('should convert active RRWebEvent to SegmentationEvent', () => {
            const event: RRWebEvent = {
                type: RRWebEventType.IncrementalSnapshot,
                timestamp: 1000,
                data: { source: RRWebEventSource.MouseMove },
            }

            const segmentationEvent = toSegmentationEvent(event)
            expect(segmentationEvent).toEqual({
                timestamp: 1000,
                isActive: true,
            })
        })

        it('should convert inactive RRWebEvent to SegmentationEvent', () => {
            const event: RRWebEvent = {
                type: RRWebEventType.Meta,
                timestamp: 1000,
                data: { href: 'https://example.com' },
            }

            const segmentationEvent = toSegmentationEvent(event)
            expect(segmentationEvent).toEqual({
                timestamp: 1000,
                isActive: false,
            })
        })

        it('should convert a FullSnapshot RRWebEvent to an active SegmentationEvent', () => {
            const event: RRWebEvent = {
                type: RRWebEventType.FullSnapshot,
                timestamp: 1000,
                data: { wireframes: [{ id: 1, type: 'wireframe' }] },
            }

            const segmentationEvent = toSegmentationEvent(event)
            expect(segmentationEvent).toEqual({
                timestamp: 1000,
                isActive: true,
            })
        })

        it('should convert a Mutation RRWebEvent to an inactive SegmentationEvent', () => {
            const event: RRWebEvent = {
                type: RRWebEventType.IncrementalSnapshot,
                timestamp: 1000,
                data: { source: RRWebEventSource.Mutation },
            }

            const segmentationEvent = toSegmentationEvent(event)
            expect(segmentationEvent).toEqual({
                timestamp: 1000,
                isActive: false,
            })
        })
    })

    describe('mobile screenshot-mode recordings', () => {
        // Mobile recordings consist almost entirely of FullSnapshot events carrying
        // wireframes plus Mutation-source incremental updates; the only interaction
        // events are occasional taps. Regression test for
        // https://github.com/PostHog/posthog/issues/91388
        const fullSnapshot = (timestamp: number): RRWebEvent =>
            ({
                type: RRWebEventType.FullSnapshot,
                timestamp,
                data: { wireframes: [{ id: 1, type: 'wireframe', x: 0, y: 0, width: 390, height: 844 }] },
            }) as RRWebEvent

        const mutation = (timestamp: number): RRWebEvent =>
            ({
                type: RRWebEventType.IncrementalSnapshot,
                timestamp,
                data: { source: RRWebEventSource.Mutation, adds: [], updates: [] },
            }) as RRWebEvent

        const tap = (timestamp: number): RRWebEvent =>
            ({
                type: RRWebEventType.IncrementalSnapshot,
                timestamp,
                data: { source: RRWebEventSource.MouseInteraction },
            }) as RRWebEvent

        it('should count a ~60s mobile recording as active, not hidden by the active duration filter', () => {
            const events: RRWebEvent[] = [
                { type: RRWebEventType.Meta, timestamp: 1000, data: { href: 'app://screen/home' } },
                fullSnapshot(1000),
                mutation(3500),
                fullSnapshot(6000),
                mutation(8500),
                fullSnapshot(11000),
                mutation(13500),
                fullSnapshot(16000),
                tap(20500),
                fullSnapshot(26000),
                mutation(28500),
                fullSnapshot(31000),
                mutation(33500),
                fullSnapshot(36000),
                mutation(38500),
                fullSnapshot(41000),
                tap(45500),
                fullSnapshot(51000),
                mutation(53500),
                fullSnapshot(56000),
                mutation(58500),
                fullSnapshot(61000),
            ]

            const activeMs = activeMillisecondsFromSegmentationEvents(events.map(toSegmentationEvent))

            // Before the fix this scored 2ms (only the two isolated taps counted),
            // so the recording fell under the list's active_seconds > 5 filter and
            // never appeared in the recordings list. The gaps at 20.5s and 45.5s are
            // >5s pauses, so the 60s span counts as three active segments: 49s total.
            expect(activeMs).toBe(49000)
            expect(activeMs).toBeGreaterThan(5000)
        })

        it('should only extend a web recording by the time from page load to first interaction', () => {
            const events: RRWebEvent[] = [
                { type: RRWebEventType.Meta, timestamp: 1000, data: { href: 'https://example.com' } },
                { type: RRWebEventType.FullSnapshot, timestamp: 1000, data: {} },
                { type: RRWebEventType.IncrementalSnapshot, timestamp: 2000, data: { source: RRWebEventSource.MouseMove } },
                { type: RRWebEventType.IncrementalSnapshot, timestamp: 3000, data: { source: RRWebEventSource.MouseMove } },
                { type: RRWebEventType.IncrementalSnapshot, timestamp: 4000, data: { source: RRWebEventSource.MouseMove } },
                { type: RRWebEventType.IncrementalSnapshot, timestamp: 4500, data: { source: RRWebEventSource.Mutation } },
            ]

            const activeMs = activeMillisecondsFromSegmentationEvents(events.map(toSegmentationEvent))

            // Before the fix this scored 2500ms (first mouse move to last event).
            // The FullSnapshot (page load) now starts the active segment, adding
            // exactly the 1000ms between page load and the first mouse move. This
            // matches the player's segmenter, which already treats FullSnapshot
            // events as active.
            expect(activeMs).toBe(3500)
        })
    })
})
