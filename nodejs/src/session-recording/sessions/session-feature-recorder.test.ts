import { DateTime } from 'luxon'

import { defaultConfig } from '../../config/config'
import { ParsedMessageData, SnapshotEvent } from '../kafka/types'
import { MouseInteractions, RRWebEventSource, RRWebEventType } from '../rrweb-types'
import { MAX_UNIQUE_VALUES, SessionFeatureRecorder, md5Hex } from './session-feature-recorder'

jest.mock('../../config/config', () => ({
    defaultConfig: {
        SESSION_RECORDING_FEATURES_ENABLED: true,
        SESSION_RECORDING_FEATURES_ROLLOUT_PERCENTAGE: 100,
    },
}))

const createMessage = (events: SnapshotEvent[], distinctId = 'user1'): ParsedMessageData => ({
    distinct_id: distinctId,
    session_id: 'session1',
    token: null,
    eventsByWindowId: { window1: events },
    eventsRange: {
        start: DateTime.fromMillis(Math.min(...events.map((e) => e.timestamp))),
        end: DateTime.fromMillis(Math.max(...events.map((e) => e.timestamp))),
    },
    snapshot_source: null,
    snapshot_library: null,
    metadata: { partition: 0, topic: 'test', offset: 0, timestamp: 0, rawSize: 0 },
})

const makeMouseMoveEvent = (
    timestamp: number,
    positions: Array<{ x: number; y: number; id?: number; timeOffset?: number }>
): SnapshotEvent =>
    ({
        type: RRWebEventType.IncrementalSnapshot,
        timestamp,
        data: {
            source: RRWebEventSource.MouseMove,
            positions: positions.map((p) => ({ x: p.x, y: p.y, id: p.id ?? 1, timeOffset: p.timeOffset ?? 0 })),
        },
    }) as unknown as SnapshotEvent

const makeScrollEvent = (timestamp: number, y: number, id = 1): SnapshotEvent =>
    ({
        type: RRWebEventType.IncrementalSnapshot,
        timestamp,
        data: {
            source: RRWebEventSource.Scroll,
            y,
            id,
        },
    }) as unknown as SnapshotEvent

const makeClickEvent = (timestamp: number, x = 100, y = 100): SnapshotEvent =>
    ({
        type: RRWebEventType.IncrementalSnapshot,
        timestamp,
        data: {
            source: RRWebEventSource.MouseInteraction,
            type: MouseInteractions.Click,
            x,
            y,
        },
    }) as unknown as SnapshotEvent

const makeKeypressEvent = (timestamp: number): SnapshotEvent =>
    ({
        type: RRWebEventType.IncrementalSnapshot,
        timestamp,
        data: {
            source: RRWebEventSource.Input,
        },
    }) as unknown as SnapshotEvent

const makeNavigationEvent = (timestamp: number, href: string): SnapshotEvent =>
    ({
        type: RRWebEventType.Meta,
        timestamp,
        data: {
            href,
        },
    }) as unknown as SnapshotEvent

const makeConsoleErrorEvent = (timestamp: number): SnapshotEvent =>
    ({
        type: RRWebEventType.Plugin,
        timestamp,
        data: {
            plugin: 'rrweb/console@1',
            payload: { level: 'error' },
        },
    }) as unknown as SnapshotEvent

describe('SessionFeatureRecorder', () => {
    let recorder: SessionFeatureRecorder

    beforeEach(() => {
        recorder = new SessionFeatureRecorder('session1', 1, 'batch1')
    })

    describe('Basic lifecycle', () => {
        it('should track startDateTime and endDateTime from message eventsRange', () => {
            const events = [makeClickEvent(1000), makeClickEvent(5000)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.startDateTime).toEqual(DateTime.fromMillis(1000))
            expect(result.endDateTime).toEqual(DateTime.fromMillis(5000))
        })

        it('should expand time range across multiple messages', () => {
            recorder.recordMessage(createMessage([makeClickEvent(3000)]))
            recorder.recordMessage(createMessage([makeClickEvent(1000)]))
            recorder.recordMessage(createMessage([makeClickEvent(5000)]))
            const result = recorder.end()!

            expect(result.startDateTime).toEqual(DateTime.fromMillis(1000))
            expect(result.endDateTime).toEqual(DateTime.fromMillis(5000))
        })

        it('should count total events across messages and windows', () => {
            const message1 = createMessage([makeClickEvent(1000), makeClickEvent(2000)])
            const message2 = createMessage([makeClickEvent(3000)])
            recorder.recordMessage(message1)
            recorder.recordMessage(message2)
            const result = recorder.end()!

            expect(result.eventCount).toBe(3)
        })

        it('should count events from multiple windows in a single message', () => {
            const message: ParsedMessageData = {
                distinct_id: 'user1',
                session_id: 'session1',
                token: null,
                eventsByWindowId: {
                    window1: [makeClickEvent(1000)],
                    window2: [makeClickEvent(2000), makeClickEvent(3000)],
                },
                eventsRange: {
                    start: DateTime.fromMillis(1000),
                    end: DateTime.fromMillis(3000),
                },
                snapshot_source: null,
                snapshot_library: null,
                metadata: { partition: 0, topic: 'test', offset: 0, timestamp: 0, rawSize: 0 },
            }
            recorder.recordMessage(message)
            const result = recorder.end()!

            expect(result.eventCount).toBe(3)
        })

        it('should default startDateTime and endDateTime to epoch when no messages recorded', () => {
            const result = recorder.end()!

            expect(result.startDateTime).toEqual(DateTime.fromMillis(0))
            expect(result.endDateTime).toEqual(DateTime.fromMillis(0))
        })

        it('should return zero counts when no events are recorded', () => {
            const result = recorder.end()!

            expect(result.eventCount).toBe(0)
            expect(result.clickCount).toBe(0)
            expect(result.keypressCount).toBe(0)
            expect(result.mousePositionCount).toBe(0)
            expect(result.scrollEventCount).toBe(0)
            expect(result.consoleErrorCount).toBe(0)
        })

        it('should throw when recordMessage is called after end()', () => {
            recorder.recordMessage(createMessage([makeClickEvent(1000)]))
            recorder.end()

            expect(() => recorder.recordMessage(createMessage([makeClickEvent(2000)]))).toThrow(
                'Cannot record message after end() has been called'
            )
        })

        it('should throw when end() is called a second time', () => {
            recorder.end()

            expect(() => recorder.end()).toThrow('end() has already been called')
        })

        it('should store the distinctId from the first message', () => {
            recorder.recordMessage(createMessage([makeClickEvent(1000)], 'alice'))

            expect(recorder.distinctId).toBe('alice')
        })

        it('should throw when accessing distinctId before any messages are recorded', () => {
            expect(() => recorder.distinctId).toThrow('No distinct_id set')
        })
    })

    describe('Mouse position tracking', () => {
        it('should count positions from a MouseMove event', () => {
            const events = [makeMouseMoveEvent(1000, [{ x: 10, y: 20 }])]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.mousePositionCount).toBe(1)
        })

        it('should accumulate statistics for multiple positions in a single event', () => {
            const events = [
                makeMouseMoveEvent(1000, [
                    { x: 3, y: 4 },
                    { x: 6, y: 8 },
                ]),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.mousePositionCount).toBe(2)
            expect(result.mouseSumX).toBe(9) // 3 + 6
            expect(result.mouseSumXSquared).toBe(45) // 9 + 36
            expect(result.mouseSumY).toBe(12) // 4 + 8
            expect(result.mouseSumYSquared).toBe(80) // 16 + 64
        })

        it('should accumulate position statistics across multiple MouseMove events', () => {
            const events = [makeMouseMoveEvent(1000, [{ x: 2, y: 3 }]), makeMouseMoveEvent(2000, [{ x: 4, y: 5 }])]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.mousePositionCount).toBe(2)
            expect(result.mouseSumX).toBe(6)
            expect(result.mouseSumY).toBe(8)
        })

        it('should not count mouse positions for non-MouseMove events', () => {
            const events = [makeScrollEvent(1000, 100), makeClickEvent(2000)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.mousePositionCount).toBe(0)
        })

        it('should skip MouseMove events with no positions array', () => {
            const event = {
                type: RRWebEventType.IncrementalSnapshot,
                timestamp: 1000,
                data: { source: RRWebEventSource.MouseMove },
            } as unknown as SnapshotEvent
            recorder.recordMessage(createMessage([event]))
            const result = recorder.end()!

            expect(result.mousePositionCount).toBe(0)
        })
    })

    describe('Mouse movement - distance and direction changes', () => {
        it('should calculate Euclidean distance traveled between positions', () => {
            // Moving from (0,0) to (3,4) = distance 5
            const events = [
                makeMouseMoveEvent(1000, [
                    { x: 0, y: 0 },
                    { x: 3, y: 4 },
                ]),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.mouseDistanceTraveled).toBeCloseTo(5)
        })

        it('should accumulate distance across multiple positions', () => {
            // (0,0) -> (3,4) = 5, then (3,4) -> (3,4+5) = (3,9) which is sqrt(0+25)=5
            const events = [
                makeMouseMoveEvent(1000, [
                    { x: 0, y: 0 },
                    { x: 3, y: 4 },
                    { x: 3, y: 9 },
                ]),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.mouseDistanceTraveled).toBeCloseTo(10)
        })

        it('should not count direction change on second position (only two points so far)', () => {
            // With only two points we get one movement vector but cannot compare to a prior vector
            const events = [
                makeMouseMoveEvent(1000, [
                    { x: 0, y: 0 },
                    { x: 10, y: 0 },
                ]),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.mouseDirectionChangeCount).toBe(0)
        })

        it('should detect direction change when dot product of consecutive vectors is negative', () => {
            // Moving right then left: dx1=10, dx2=-10 => dot product negative => direction change
            const events = [
                makeMouseMoveEvent(1000, [
                    { x: 0, y: 0 },
                    { x: 10, y: 0 },
                    { x: 0, y: 0 },
                ]),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.mouseDirectionChangeCount).toBe(1)
        })

        it('should not flag direction change when movement continues in same direction', () => {
            // Straight line: same direction vectors => no direction change
            const events = [
                makeMouseMoveEvent(1000, [
                    { x: 0, y: 0 },
                    { x: 5, y: 0 },
                    { x: 10, y: 0 },
                ]),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.mouseDirectionChangeCount).toBe(0)
        })

        it('should accumulate direction changes across multiple events', () => {
            const events = [
                // First event establishes direction going right
                makeMouseMoveEvent(1000, [
                    { x: 0, y: 0 },
                    { x: 10, y: 0 },
                ]),
                // Second event reverses direction (left) - direction change
                makeMouseMoveEvent(2000, [{ x: 0, y: 0 }]),
                // Third continues in same leftward direction - no change
                makeMouseMoveEvent(3000, [{ x: -10, y: 0 }]),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.mouseDirectionChangeCount).toBe(1)
        })
    })

    describe('Mouse velocity', () => {
        it('should compute velocity as distance divided by dt using timeOffset', () => {
            // Two positions: (0,0) at t=1000, (3,4) at t=1000+200=1200, distance=5, dt=200
            const events = [
                makeMouseMoveEvent(1000, [
                    { x: 0, y: 0, timeOffset: 0 },
                    { x: 3, y: 4, timeOffset: 200 },
                ]),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            const expectedVelocity = 5 / 200
            expect(result.mouseVelocityCount).toBe(1)
            expect(result.mouseVelocitySum).toBeCloseTo(expectedVelocity)
            expect(result.mouseVelocitySumOfSquares).toBeCloseTo(expectedVelocity * expectedVelocity)
        })

        it('should skip velocity calculation when dt is zero', () => {
            // Two positions at same timestamp with same timeOffset => dt=0
            const events = [
                makeMouseMoveEvent(1000, [
                    { x: 0, y: 0, timeOffset: 0 },
                    { x: 10, y: 0, timeOffset: 0 },
                ]),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.mouseVelocityCount).toBe(0)
        })

        it('should accumulate velocity statistics across multiple position pairs', () => {
            const events = [
                makeMouseMoveEvent(1000, [
                    { x: 0, y: 0, timeOffset: 0 },
                    { x: 3, y: 4, timeOffset: 100 }, // velocity = 5/100 = 0.05
                    { x: 3, y: 4 + 5, timeOffset: 200 }, // distance=5, dt=100, velocity=0.05
                ]),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.mouseVelocityCount).toBe(2)
            expect(result.mouseVelocitySum).toBeCloseTo(0.1)
        })

        it('should use the event timestamp combined with timeOffset for velocity', () => {
            // Two separate events: first positions at t=1000+0=1000, second at t=2000+0=2000
            // Distance (0,0)->(0,100)=100, dt=1000, velocity=0.1
            const events = [
                makeMouseMoveEvent(1000, [{ x: 0, y: 0, timeOffset: 0 }]),
                makeMouseMoveEvent(2000, [{ x: 0, y: 100, timeOffset: 0 }]),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.mouseVelocityCount).toBe(1)
            expect(result.mouseVelocitySum).toBeCloseTo(0.1)
        })
    })

    describe('Scroll tracking', () => {
        it('should count scroll events', () => {
            const events = [makeScrollEvent(1000, 0), makeScrollEvent(2000, 100), makeScrollEvent(3000, 200)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.scrollEventCount).toBe(3)
        })

        it('should accumulate total scroll magnitude', () => {
            // 0 -> 100 -> 50: magnitudes 100 + 50 = 150
            const events = [makeScrollEvent(1000, 0), makeScrollEvent(2000, 100), makeScrollEvent(3000, 50)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.totalScrollMagnitude).toBe(150)
        })

        it('should count direction reversal when scroll direction changes', () => {
            // down then up = reversal
            const events = [makeScrollEvent(1000, 0), makeScrollEvent(2000, 100), makeScrollEvent(3000, 50)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.scrollDirectionReversalCount).toBe(1)
        })

        it('should not count direction reversal when scrolling in same direction', () => {
            const events = [makeScrollEvent(1000, 0), makeScrollEvent(2000, 100), makeScrollEvent(3000, 200)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.scrollDirectionReversalCount).toBe(0)
        })

        it('should flag rapid scroll reversal when direction changes within 500ms', () => {
            const events = [
                makeScrollEvent(1000, 0),
                makeScrollEvent(1200, 100), // down
                makeScrollEvent(1400, 50), // up within 200ms => rapid reversal
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.rapidScrollReversalCount).toBe(1)
        })

        it('should not flag rapid reversal when direction changes after 500ms or more', () => {
            const events = [
                makeScrollEvent(1000, 0),
                makeScrollEvent(1200, 100), // down
                makeScrollEvent(1700, 50), // up at exactly 500ms later - NOT rapid (< 500 required)
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.rapidScrollReversalCount).toBe(0)
        })

        it('should reset position tracking when scroll element ID changes', () => {
            // Scroll element 1: 0 -> 200 (down), then element 2: 300 (new baseline, no delta)
            // Then element 2: 100 (up from 300). That single direction from element 2 won't produce a reversal.
            const events = [
                makeScrollEvent(1000, 0, 1), // element 1, baseline
                makeScrollEvent(2000, 200, 1), // element 1, down
                makeScrollEvent(3000, 300, 2), // element 2, new baseline (reset)
                makeScrollEvent(4000, 100, 2), // element 2, up
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            // Only the two element-2 events create one direction; no prior direction => no reversal
            expect(result.scrollDirectionReversalCount).toBe(0)
        })

        it('should reset lastScrollY and lastScrollDirection when element ID changes mid-stream', () => {
            // element 1: down then up => 1 reversal
            // element 2 (id change): down then up => 1 reversal
            // Total = 2 reversals, not 3 (the id change should not trigger a cross-element comparison)
            const events = [
                makeScrollEvent(1000, 0, 1),
                makeScrollEvent(2000, 100, 1), // down
                makeScrollEvent(3000, 50, 1), // up => reversal 1
                makeScrollEvent(4000, 0, 2), // element 2, new baseline
                makeScrollEvent(5000, 100, 2), // down
                makeScrollEvent(6000, 50, 2), // up => reversal 2
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.scrollDirectionReversalCount).toBe(2)
        })

        it('should not include scroll events with undefined y in magnitude or direction tracking', () => {
            const eventWithoutY = {
                type: RRWebEventType.IncrementalSnapshot,
                timestamp: 1000,
                data: { source: RRWebEventSource.Scroll, id: 1 },
            } as unknown as SnapshotEvent
            recorder.recordMessage(createMessage([eventWithoutY]))
            const result = recorder.end()!

            // scrollEventCount still increments, but no magnitude/direction tracking
            expect(result.scrollEventCount).toBe(1)
            expect(result.totalScrollMagnitude).toBe(0)
            expect(result.scrollDirectionReversalCount).toBe(0)
        })
    })

    describe('Click frustration - rage clicks', () => {
        it('should not count rage clicks for fewer than 3 clicks', () => {
            const events = [makeClickEvent(0, 10, 10), makeClickEvent(100, 10, 10)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.rageClickCount).toBe(0)
        })

        it('should count rage click on the 3rd click within 1s and 30px radius', () => {
            const events = [makeClickEvent(0, 10, 10), makeClickEvent(300, 10, 10), makeClickEvent(600, 10, 10)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.rageClickCount).toBe(1)
        })

        it('should increment rage click count for each additional click beyond the 3rd', () => {
            const events = [
                makeClickEvent(0, 10, 10),
                makeClickEvent(200, 10, 10),
                makeClickEvent(400, 10, 10), // rage click #1
                makeClickEvent(600, 10, 10), // rage click #2
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.rageClickCount).toBe(2)
        })

        it('should not count rage click when clicks are more than 1000ms apart', () => {
            const events = [
                makeClickEvent(0, 10, 10),
                makeClickEvent(500, 10, 10),
                makeClickEvent(1500, 10, 10), // resets due to >1000ms gap
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.rageClickCount).toBe(0)
        })

        it('should not count rage click when clicks are more than 30px apart', () => {
            const events = [
                makeClickEvent(0, 0, 0),
                makeClickEvent(100, 50, 0), // >30px apart
                makeClickEvent(200, 50, 0),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.rageClickCount).toBe(0)
        })
    })

    describe('Click frustration - dead clicks', () => {
        it('should count a dead click when a single isolated click has no URL change before the next click', () => {
            // Click 1 (isolated, no url change), then click 2 (triggers evaluation of click 1)
            const events = [makeClickEvent(0), makeClickEvent(5000)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.deadClickCount).toBe(1)
        })

        it('should not count dead click when URL changes before the next click', () => {
            const events = [
                makeClickEvent(1000),
                makeNavigationEvent(2000, 'https://example.com/page2'),
                makeClickEvent(5000),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.deadClickCount).toBe(0)
        })

        it('should not count dead click when multiple clicks happen close together (rage click group)', () => {
            const events = [
                makeClickEvent(0, 10, 10),
                makeClickEvent(300, 10, 10), // consecutive with first => consecutiveClickCount=2
                makeClickEvent(10000), // triggers evaluation: consecutiveClickCount was 2, not 1
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.deadClickCount).toBe(0)
        })
    })

    describe('Click and keypress counts', () => {
        it('should count all click events', () => {
            const events = [makeClickEvent(1000), makeClickEvent(2000), makeClickEvent(3000)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.clickCount).toBe(3)
        })

        it('should count keypress events', () => {
            const events = [makeKeypressEvent(1000), makeKeypressEvent(2000)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.keypressCount).toBe(2)
        })

        it('should count mouse activity from MouseInteraction, MouseMove, and TouchMove sources', () => {
            const touchMoveEvent = {
                type: RRWebEventType.IncrementalSnapshot,
                timestamp: 3000,
                data: { source: RRWebEventSource.TouchMove },
            } as unknown as SnapshotEvent
            const events = [makeClickEvent(1000), makeMouseMoveEvent(2000, [{ x: 1, y: 1 }]), touchMoveEvent]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.mouseActivityCount).toBe(3)
        })

        it('should not count scroll events as mouse activity', () => {
            const events = [makeScrollEvent(1000, 100)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.mouseActivityCount).toBe(0)
        })
    })

    describe('Inter-action timing', () => {
        it('should record a gap between two click events', () => {
            const events = [makeClickEvent(1000), makeClickEvent(4000)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.interActionGapCount).toBe(1)
            expect(result.interActionGapSumMs).toBe(3000)
            expect(result.interActionGapSumOfSquaresMs).toBe(9_000_000)
        })

        it('should record gaps between keypresses', () => {
            const events = [makeKeypressEvent(1000), makeKeypressEvent(2000), makeKeypressEvent(4000)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.interActionGapCount).toBe(2)
            expect(result.interActionGapSumMs).toBe(3000) // 1000 + 2000
        })

        it('should record gaps between clicks and keypresses', () => {
            const events = [makeClickEvent(1000), makeKeypressEvent(3000)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.interActionGapCount).toBe(1)
            expect(result.interActionGapSumMs).toBe(2000)
        })

        it('should track maxIdleGapMs as the largest gap seen', () => {
            const events = [
                makeClickEvent(1000),
                makeClickEvent(2500), // gap 1500
                makeClickEvent(5500), // gap 3000
                makeClickEvent(7000), // gap 1500
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.maxIdleGapMs).toBe(3000)
        })

        it('should not record a gap for the first action', () => {
            const events = [makeClickEvent(1000)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.interActionGapCount).toBe(0)
            expect(result.interActionGapSumMs).toBe(0)
        })

        it('should not record a gap when timestamp difference is zero', () => {
            // Two clicks at same timestamp - gap = 0, should not be recorded
            const events = [makeClickEvent(1000), makeClickEvent(1000)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.interActionGapCount).toBe(0)
        })

        it('should not count scroll events as inter-action timing triggers', () => {
            // Scroll between two clicks should not appear in gap tracking
            const events = [makeClickEvent(1000), makeScrollEvent(2000, 100), makeClickEvent(4000)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            // Gap should be 3000 (click to click), not 1000+2000
            expect(result.interActionGapCount).toBe(1)
            expect(result.interActionGapSumMs).toBe(3000)
        })
    })

    describe('Navigation tracking', () => {
        it('should count each navigation event as a page visit', () => {
            const events = [
                makeNavigationEvent(1000, 'https://example.com/'),
                makeNavigationEvent(2000, 'https://example.com/about'),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.pageVisitCount).toBe(2)
        })

        it('should count revisit when same URL is visited more than once', () => {
            const events = [
                makeNavigationEvent(1000, 'https://example.com/'),
                makeNavigationEvent(2000, 'https://example.com/about'),
                makeNavigationEvent(3000, 'https://example.com/'), // revisit
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.visitedUrls).toEqual([md5Hex('https://example.com/'), md5Hex('https://example.com/about')])
        })

        it('should cap unique visited URLs at MAX_UNIQUE_VALUES', () => {
            const events = Array.from({ length: MAX_UNIQUE_VALUES + 50 }, (_, i) =>
                makeNavigationEvent(1000 + i, `https://example.com/page-${i}`)
            )
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.visitedUrls).toHaveLength(MAX_UNIQUE_VALUES)
            expect(result.pageVisitCount).toBe(MAX_UNIQUE_VALUES + 50)
            expect(result.visitedUrls[0]).toMatch(/^[0-9a-f]{32}$/)
        })

        it('should count quickBack when a different URL is navigated to within 2000ms', () => {
            const events = [
                makeNavigationEvent(1000, 'https://example.com/'),
                makeNavigationEvent(2500, 'https://example.com/about'), // 1500ms later => quickBack
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.quickBackCount).toBe(1)
        })

        it('should not count quickBack when URL does not change', () => {
            const events = [
                makeNavigationEvent(1000, 'https://example.com/'),
                makeNavigationEvent(1500, 'https://example.com/'), // same URL
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.quickBackCount).toBe(0)
        })

        it('should not count quickBack when navigation gap is 2000ms or more', () => {
            const events = [
                makeNavigationEvent(1000, 'https://example.com/'),
                makeNavigationEvent(3001, 'https://example.com/about'), // >2000ms later
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.quickBackCount).toBe(0)
        })

        it('should set urlChangedSinceLastClick to allow dead click detection to be cleared', () => {
            // Click, then navigation, then another click => first click should NOT be dead
            const events = [
                makeClickEvent(1000),
                makeNavigationEvent(2000, 'https://example.com/page2'),
                makeClickEvent(5000),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.deadClickCount).toBe(0)
        })
    })

    describe('Console error tracking', () => {
        it('should count console error plugin events', () => {
            const events = [makeConsoleErrorEvent(1000), makeConsoleErrorEvent(2000)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.consoleErrorCount).toBe(2)
        })

        it('should not count plugin events from other plugins as console errors', () => {
            const event = {
                type: RRWebEventType.Plugin,
                timestamp: 1000,
                data: { plugin: 'some-other-plugin', payload: { level: 'error' } },
            } as unknown as SnapshotEvent
            recorder.recordMessage(createMessage([event]))
            const result = recorder.end()!

            expect(result.consoleErrorCount).toBe(0)
        })

        it('should not count non-error log levels as console errors', () => {
            const infoEvent = {
                type: RRWebEventType.Plugin,
                timestamp: 1000,
                data: { plugin: 'rrweb/console@1', payload: { level: 'info' } },
            } as unknown as SnapshotEvent
            recorder.recordMessage(createMessage([infoEvent]))
            const result = recorder.end()!

            expect(result.consoleErrorCount).toBe(0)
        })

        it('should count consoleErrorAfterClickCount when error occurs within 5s of a click', () => {
            const events = [
                makeClickEvent(1000),
                makeConsoleErrorEvent(5999), // 4999ms after click => within 5s
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.consoleErrorAfterClickCount).toBe(1)
        })

        it('should count consoleErrorAfterClickCount when error occurs within 5s of a keypress', () => {
            const events = [
                makeKeypressEvent(1000),
                makeConsoleErrorEvent(3000), // 2000ms after keypress => within 5s
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.consoleErrorAfterClickCount).toBe(1)
        })

        it('should not count consoleErrorAfterClickCount when error occurs 5s or more after last user action', () => {
            const events = [
                makeClickEvent(1000),
                makeConsoleErrorEvent(6001), // 5001ms after click => outside 5s window
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.consoleErrorCount).toBe(1)
            expect(result.consoleErrorAfterClickCount).toBe(0)
        })

        it('should count consoleErrorAfterClickCount when error occurs exactly at the 5s boundary', () => {
            // timeSinceAction >= 0 && < 5000 means at exactly 5000ms it should NOT count
            const events = [
                makeClickEvent(1000),
                makeConsoleErrorEvent(6000), // exactly 5000ms after click => NOT within window
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.consoleErrorAfterClickCount).toBe(0)
        })

        it('should not count consoleErrorAfterClickCount when error precedes any user action', () => {
            const events = [
                makeConsoleErrorEvent(1000), // no prior click/keypress
                makeClickEvent(2000),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.consoleErrorAfterClickCount).toBe(0)
        })

        it('should use the most recent user action timestamp for error proximity', () => {
            const events = [
                makeClickEvent(1000),
                makeKeypressEvent(5000), // more recent action
                makeConsoleErrorEvent(7000), // 2000ms after keypress (within 5s), but 6000ms after click
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.consoleErrorAfterClickCount).toBe(1)
        })
    })

    describe('Network request tracking', () => {
        const makeRRWebNetworkEvent = (
            timestamp: number,
            requests: Array<{ duration?: number; status?: number; responseStatus?: number }>
        ): SnapshotEvent =>
            ({
                type: RRWebEventType.Plugin,
                timestamp,
                data: {
                    plugin: 'rrweb/network@1',
                    payload: { requests },
                },
            }) as unknown as SnapshotEvent

        const makePostHogNetworkEvent = (timestamp: number, duration?: number, status?: number): SnapshotEvent =>
            ({
                type: RRWebEventType.Plugin,
                timestamp,
                data: {
                    plugin: 'posthog/network@1',
                    payload: { 39: duration, 21: status },
                },
            }) as unknown as SnapshotEvent

        it('should count requests from rrweb/network@1 plugin', () => {
            const events = [
                makeRRWebNetworkEvent(1000, [
                    { duration: 100, status: 200 },
                    { duration: 200, status: 200 },
                ]),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.networkRequestCount).toBe(2)
        })

        it('should count requests from posthog/network@1 plugin', () => {
            const events = [makePostHogNetworkEvent(1000, 150, 200), makePostHogNetworkEvent(2000, 300, 200)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.networkRequestCount).toBe(2)
        })

        it('should count failed requests with status >= 400', () => {
            const events = [
                makeRRWebNetworkEvent(1000, [
                    { duration: 100, status: 200 },
                    { duration: 100, status: 404 },
                    { duration: 100, status: 500 },
                ]),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.networkRequestCount).toBe(3)
            expect(result.networkFailedRequestCount).toBe(2)
        })

        it('should use responseStatus when status is not present', () => {
            const events = [makeRRWebNetworkEvent(1000, [{ duration: 100, responseStatus: 503 }])]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.networkFailedRequestCount).toBe(1)
        })

        it('should accumulate duration sufficient statistics', () => {
            const events = [
                makeRRWebNetworkEvent(1000, [
                    { duration: 100, status: 200 },
                    { duration: 300, status: 200 },
                ]),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.networkRequestDurationCount).toBe(2)
            expect(result.networkRequestDurationSum).toBe(400)
            expect(result.networkRequestDurationSumOfSquares).toBe(100 * 100 + 300 * 300)
        })

        it('should skip duration stats when duration is missing or zero', () => {
            const events = [makeRRWebNetworkEvent(1000, [{ status: 200 }, { duration: 0, status: 200 }])]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.networkRequestCount).toBe(2)
            expect(result.networkRequestDurationCount).toBe(0)
        })

        it('should skip rrweb/network@1 events with no requests array', () => {
            const event = {
                type: RRWebEventType.Plugin,
                timestamp: 1000,
                data: { plugin: 'rrweb/network@1', payload: {} },
            } as unknown as SnapshotEvent
            recorder.recordMessage(createMessage([event]))
            const result = recorder.end()!

            expect(result.networkRequestCount).toBe(0)
        })

        it('should not count non-network plugin events', () => {
            const events = [makeConsoleErrorEvent(1000)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.networkRequestCount).toBe(0)
        })

        it('should aggregate across both plugin types', () => {
            const events = [
                makeRRWebNetworkEvent(1000, [{ duration: 100, status: 200 }]),
                makePostHogNetworkEvent(2000, 200, 500),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.networkRequestCount).toBe(2)
            expect(result.networkFailedRequestCount).toBe(1)
            expect(result.networkRequestDurationSum).toBe(300)
        })
    })

    describe('Scroll depth (maxScrollY)', () => {
        it('should track the maximum scroll Y position', () => {
            const events = [makeScrollEvent(1000, 100), makeScrollEvent(2000, 500), makeScrollEvent(3000, 300)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.maxScrollY).toBe(500)
        })

        it('should return 0 when no scroll events occur', () => {
            recorder.recordMessage(createMessage([makeClickEvent(1000)]))
            const result = recorder.end()!

            expect(result.maxScrollY).toBe(0)
        })

        it('should track maxScrollY across multiple scroll targets', () => {
            const events = [makeScrollEvent(1000, 200, 1), makeScrollEvent(2000, 800, 2), makeScrollEvent(3000, 400, 1)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.maxScrollY).toBe(800)
        })
    })

    describe('Unique click targets', () => {
        const makeClickEventWithTarget = (timestamp: number, id: number, x = 100, y = 100): SnapshotEvent =>
            ({
                type: RRWebEventType.IncrementalSnapshot,
                timestamp,
                data: {
                    source: RRWebEventSource.MouseInteraction,
                    type: MouseInteractions.Click,
                    x,
                    y,
                    id,
                },
            }) as unknown as SnapshotEvent

        it('should collect unique click target ids by rrweb node id', () => {
            const events = [
                makeClickEventWithTarget(1000, 10),
                makeClickEventWithTarget(2000, 20),
                makeClickEventWithTarget(3000, 10), // same target as first
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.clickTargetIds).toEqual(expect.arrayContaining([10, 20]))
            expect(result.clickTargetIds).toHaveLength(2)
        })

        it('should return empty array when no clicks occur', () => {
            recorder.recordMessage(createMessage([makeKeypressEvent(1000)]))
            const result = recorder.end()!

            expect(result.clickTargetIds).toEqual([])
        })

        it('should collect each distinct target exactly once across messages', () => {
            recorder.recordMessage(createMessage([makeClickEventWithTarget(1000, 5)]))
            recorder.recordMessage(createMessage([makeClickEventWithTarget(2000, 5)]))
            recorder.recordMessage(createMessage([makeClickEventWithTarget(3000, 15)]))
            const result = recorder.end()!

            expect(result.clickTargetIds).toEqual(expect.arrayContaining([5, 15]))
            expect(result.clickTargetIds).toHaveLength(2)
        })

        it('should cap unique click target ids at MAX_UNIQUE_VALUES', () => {
            const events = Array.from({ length: MAX_UNIQUE_VALUES + 50 }, (_, i) =>
                makeClickEventWithTarget(1000 + i, i)
            )
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.clickTargetIds).toHaveLength(MAX_UNIQUE_VALUES)
            expect(result.clickCount).toBe(MAX_UNIQUE_VALUES + 50)
        })
    })

    describe('Text selection tracking', () => {
        const makeSelectionEvent = (timestamp: number): SnapshotEvent =>
            ({
                type: RRWebEventType.IncrementalSnapshot,
                timestamp,
                data: { source: RRWebEventSource.Selection },
            }) as unknown as SnapshotEvent

        it('should count text selection events', () => {
            const events = [makeSelectionEvent(1000), makeSelectionEvent(2000)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.textSelectionCount).toBe(2)
        })

        it('should return 0 when no selection events occur', () => {
            recorder.recordMessage(createMessage([makeClickEvent(1000)]))
            const result = recorder.end()!

            expect(result.textSelectionCount).toBe(0)
        })

        it('should not count other IncrementalSnapshot sources as selections', () => {
            const events = [makeScrollEvent(1000, 100), makeMouseMoveEvent(2000, [{ x: 1, y: 1 }])]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.textSelectionCount).toBe(0)
        })
    })

    describe('New features return zero by default', () => {
        it('should return zero for all new features when no events are recorded', () => {
            const result = recorder.end()!

            expect(result.networkRequestCount).toBe(0)
            expect(result.networkFailedRequestCount).toBe(0)
            expect(result.networkRequestDurationSum).toBe(0)
            expect(result.networkRequestDurationSumOfSquares).toBe(0)
            expect(result.networkRequestDurationCount).toBe(0)
            expect(result.maxScrollY).toBe(0)
            expect(result.clickTargetIds).toEqual([])
            expect(result.visitedUrls).toEqual([])
            expect(result.textSelectionCount).toBe(0)
        })
    })

    describe('Independence of trackers', () => {
        it('should process scroll events without skipping click tracking in the same batch', () => {
            const events = [makeScrollEvent(1000, 100), makeClickEvent(2000), makeClickEvent(3000)]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.scrollEventCount).toBe(1)
            expect(result.clickCount).toBe(2)
        })

        it('should process mouse move events without skipping keypress tracking', () => {
            const events = [
                makeMouseMoveEvent(1000, [{ x: 5, y: 5 }]),
                makeKeypressEvent(2000),
                makeKeypressEvent(3000),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.mousePositionCount).toBe(1)
            expect(result.keypressCount).toBe(2)
        })

        it('should process console error events alongside click tracking simultaneously', () => {
            const events = [
                makeClickEvent(1000),
                makeConsoleErrorEvent(2000), // within 5s of click
                makeClickEvent(3000),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.clickCount).toBe(2)
            expect(result.consoleErrorCount).toBe(1)
            expect(result.consoleErrorAfterClickCount).toBe(1)
        })

        it('should process navigation events alongside scroll tracking simultaneously', () => {
            const events = [
                makeScrollEvent(1000, 0),
                makeNavigationEvent(1500, 'https://example.com/'),
                makeScrollEvent(2000, 100),
                makeNavigationEvent(3000, 'https://example.com/about'),
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.scrollEventCount).toBe(2)
            expect(result.pageVisitCount).toBe(2)
        })

        it('should process all tracker categories in a mixed event stream', () => {
            const events = [
                makeMouseMoveEvent(1000, [
                    { x: 0, y: 0 },
                    { x: 10, y: 0 },
                ]),
                makeScrollEvent(1500, 0),
                makeScrollEvent(2000, 200),
                makeClickEvent(2500, 10, 10),
                makeClickEvent(2700, 10, 10),
                makeClickEvent(2900, 10, 10),
                makeKeypressEvent(3500),
                makeNavigationEvent(4000, 'https://example.com/'),
                makeConsoleErrorEvent(5000), // 1500ms after keypress => within 5s
            ]
            recorder.recordMessage(createMessage(events))
            const result = recorder.end()!

            expect(result.mousePositionCount).toBe(2)
            expect(result.scrollEventCount).toBe(2)
            expect(result.clickCount).toBe(3)
            expect(result.rageClickCount).toBe(1)
            expect(result.keypressCount).toBe(1)
            expect(result.pageVisitCount).toBe(1)
            expect(result.consoleErrorCount).toBe(1)
            expect(result.consoleErrorAfterClickCount).toBe(1)
        })
    })

    describe('Rollout gating', () => {
        afterEach(() => {
            ;(defaultConfig as any).SESSION_RECORDING_FEATURES_ROLLOUT_PERCENTAGE = 100
        })

        it('should return null from end() when rollout is 0', () => {
            ;(defaultConfig as any).SESSION_RECORDING_FEATURES_ROLLOUT_PERCENTAGE = 0
            const gatedRecorder = new SessionFeatureRecorder('session1', 1, 'batch1')
            gatedRecorder.recordMessage(createMessage([makeClickEvent(1000)]))
            expect(gatedRecorder.end()).toBeNull()
        })

        it('should return features when rollout is 100', () => {
            ;(defaultConfig as any).SESSION_RECORDING_FEATURES_ROLLOUT_PERCENTAGE = 100
            const gatedRecorder = new SessionFeatureRecorder('session1', 1, 'batch1')
            gatedRecorder.recordMessage(createMessage([makeClickEvent(1000)]))
            expect(gatedRecorder.end()).not.toBeNull()
        })

        it('should be deterministic for the same session ID', () => {
            ;(defaultConfig as any).SESSION_RECORDING_FEATURES_ROLLOUT_PERCENTAGE = 50
            const results = Array.from({ length: 10 }, () => {
                const r = new SessionFeatureRecorder('fixed-session-id', 1, 'batch1')
                return r.end()
            })
            const allNull = results.every((r) => r === null)
            const allNonNull = results.every((r) => r !== null)
            expect(allNull || allNonNull).toBe(true)
        })
    })
})
