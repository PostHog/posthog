import { RRWebEvent } from '../../../types'
import { RRWebEventSource, RRWebEventType } from './rrweb-types'
import {
    activeMilliseconds,
} from './segmentation'

describe('segmentation', () => {
    describe('activeMilliseconds', () => {
        it('should return 0 for empty events array', () => {
            expect(activeMilliseconds([])).toBe(0)
        })

        it('should return 0 when there are no active events', () => {
            const events: RRWebEvent[] = [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: { href: 'https://example.com' },
                },
                {
                    type: RRWebEventType.Meta,
                    timestamp: 2000,
                    data: { href: 'https://example.com/page2' },
                },
            ]

            expect(activeMilliseconds(events)).toBe(0)
        })

        it('should calculate active time for a single active event', () => {
            const events: RRWebEvent[] = [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: RRWebEventSource.MouseMove },
                },
            ]

            // This is a special case where we cound duration of active segments with one event as 1ms
            expect(activeMilliseconds(events)).toBe(1)
        })

        it('should calculate active time for consecutive active events', () => {
            const events: RRWebEvent[] = [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: RRWebEventSource.MouseMove },
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 2000, // 1 second after first event
                    data: { source: RRWebEventSource.MouseMove },
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 3000, // 1 second after second event
                    data: { source: RRWebEventSource.MouseInteraction },
                },
            ]

            // Active time should be the difference between the first and last active event
            expect(activeMilliseconds(events)).toBe(2000)
        })

        it('should handle inactive periods between active events', () => {
            const events: RRWebEvent[] = [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: RRWebEventSource.MouseMove },
                },
                {
                    type: RRWebEventType.Meta,
                    timestamp: 2100,
                    data: { href: 'https://example.com' },
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 6001, // 5 seconds after the last active event (exceeds activity threshold)
                    data: { source: RRWebEventSource.MouseMove },
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 7001, // 1 second after previous active event
                    data: { source: RRWebEventSource.MouseInteraction },
                },
            ]

            // Should create two separate active segments: 1100ms for the first and 1000ms for the second
            expect(activeMilliseconds(events)).toBe(2100)
        })

        it('should handle events that are not in chronological order', () => {
            const events: RRWebEvent[] = [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 3000,
                    data: { source: RRWebEventSource.MouseInteraction },
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000, // Out of order
                    data: { source: RRWebEventSource.MouseMove },
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 2000,
                    data: { source: RRWebEventSource.MouseMove },
                },
            ]

            // Events should be sorted and active time calculated correctly
            expect(activeMilliseconds(events)).toBe(2000)
        })

        it('should handle mixed active and inactive events', () => {
            const events: RRWebEvent[] = [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 500,
                    data: { href: 'https://example.com' },
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: RRWebEventSource.MouseMove },
                },
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1500,
                    data: { href: 'https://example.com/page2' },
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 2000,
                    data: { source: RRWebEventSource.MouseInteraction },
                },
                {
                    type: RRWebEventType.Meta,
                    timestamp: 2500,
                    data: { href: 'https://example.com/page3' },
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 3000,
                    data: { source: RRWebEventSource.Scroll },
                },
            ]

            // Active time should be the difference between the first and last active event
            expect(activeMilliseconds(events)).toBe(2000)
        })

        it('should maintain one segment when inactive events are within activity threshold', () => {
            const events: RRWebEvent[] = [
                // First active event
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: RRWebEventSource.MouseMove },
                },
                // Inactive events at 1-second intervals
                {
                    type: RRWebEventType.Meta,
                    timestamp: 2000, // 1 second after first event
                    data: { href: 'https://example.com/page1' },
                },
                {
                    type: RRWebEventType.Meta,
                    timestamp: 3000, // 2 seconds after first event
                    data: { href: 'https://example.com/page2' },
                },
                {
                    type: RRWebEventType.Meta,
                    timestamp: 4000, // 3 seconds after first event
                    data: { href: 'https://example.com/page3' },
                },
                {
                    type: RRWebEventType.Meta,
                    timestamp: 5000, // 4 seconds after first event
                    data: { href: 'https://example.com/page4' },
                },
                {
                    type: RRWebEventType.Meta,
                    timestamp: 6000, // 5 seconds after first event
                    data: { href: 'https://example.com/page5' },
                },
                {
                    type: RRWebEventType.Meta,
                    timestamp: 6001, // Just after the last inactive event
                    data: { href: 'https://example.com/page6' },
                },
            ]

            // Should create one active segment with duration of 5000ms
            expect(activeMilliseconds(events)).toBe(5000)
        })
    })
})
