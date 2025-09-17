import { RRWebEvent } from '../../../types'
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
    })
})
