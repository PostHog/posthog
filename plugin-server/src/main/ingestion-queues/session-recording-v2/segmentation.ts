/**
 * This file is a cut-down version of the segmenter.ts
 * https://github.com/PostHog/posthog/blob/db2deaf650d2eca9addba5e3f304a17a21041f25/frontend/src/scenes/session-recordings/player/utils/segmenter.ts
 *
 * It has been modified to not need the same dependencies
 * Any changes may need to be sync'd between the two
 */
import { SnapshotEvent } from './kafka/types'
import { RRWebEventSource, RRWebEventType } from './rrweb-types'

const activeSources = [
    RRWebEventSource.MouseMove,
    RRWebEventSource.MouseInteraction,
    RRWebEventSource.Scroll,
    RRWebEventSource.ViewportResize,
    RRWebEventSource.Input,
    RRWebEventSource.TouchMove,
    RRWebEventSource.MediaInteraction,
    RRWebEventSource.Drag,
]

const ACTIVITY_THRESHOLD_MS = 5000

export interface RRWebPartialData {
    href?: string
    source?: number
    payload?: Record<string, any>
    plugin?: string
}

/**
 * Simplified event with just the essential information for activity tracking
 */
export interface SegmentationEvent {
    timestamp: number
    isActive: boolean
}

interface RecordingSegment {
    kind: 'window' | 'buffer' | 'gap'
    startTimestamp: number // Epoch time that the segment starts
    endTimestamp: number // Epoch time that the segment ends
    durationMs: number
    isActive: boolean
}

/**
 * Checks if an event is an active event (indicates user activity)
 */
const isActiveEvent = (event: SnapshotEvent): boolean => {
    const eventData = event as { type?: number; data?: { source?: number } } | undefined
    const type = eventData?.type
    const source = eventData?.data?.source

    return type === RRWebEventType.IncrementalSnapshot && activeSources.includes(source ?? -1)
}

/**
 * Converts an RRWebEvent to a simplified SegmentationEvent with just timestamp and activity status
 */
export const toSegmentationEvent = (event: SnapshotEvent): SegmentationEvent => {
    return {
        timestamp: event.timestamp,
        isActive: isActiveEvent(event),
    }
}

/**
 * Creates segments from a list of active events, identifying periods of activity and inactivity
 */
export const createSegmentsFromSegmentationEvents = (segmentationEvents: SegmentationEvent[]): RecordingSegment[] => {
    const sortedEvents = [...segmentationEvents].sort((a, b) => a.timestamp - b.timestamp)

    const segments: RecordingSegment[] = []
    let activeSegment: RecordingSegment | null = null
    let lastActiveEventTimestamp = 0

    sortedEvents.forEach((event) => {
        // When do we create a new segment?
        // 1. If we don't have one yet
        let isNewSegment = !activeSegment

        // 2. If it is currently inactive but a new "active" event comes in
        if (event.isActive && !activeSegment?.isActive) {
            isNewSegment = true
        }

        // 3. If it is currently active but no new active event has been seen for the activity threshold
        if (activeSegment?.isActive && lastActiveEventTimestamp + ACTIVITY_THRESHOLD_MS < event.timestamp) {
            isNewSegment = true
        }

        // NOTE: We have to make sure that we set this _after_ we use it
        lastActiveEventTimestamp = event.isActive ? event.timestamp : lastActiveEventTimestamp

        if (isNewSegment) {
            if (activeSegment) {
                segments.push(activeSegment)
            }

            activeSegment = {
                kind: 'window',
                startTimestamp: event.timestamp,
                endTimestamp: event.timestamp,
                durationMs: 0,
                isActive: event.isActive,
            }
        } else if (activeSegment) {
            activeSegment.endTimestamp = event.timestamp
            activeSegment.durationMs = activeSegment.endTimestamp - activeSegment.startTimestamp
        }
    })

    if (activeSegment) {
        segments.push(activeSegment)
    }

    return segments
}

/**
 * Calculates the total active time in milliseconds from a list of segmentation events
 */
export const activeMillisecondsFromSegmentationEvents = (segmentationEvents: SegmentationEvent[]): number => {
    const segments = createSegmentsFromSegmentationEvents(segmentationEvents)
    return activeMillisecondsFromSegments(segments)
}

const activeMillisecondsFromSegments = (segments: RecordingSegment[]): number => {
    return segments.reduce((acc, segment) => {
        if (segment.isActive) {
            // if the segment is active but has no duration we count it as 1ms
            // to distinguish it from segments with no activity at all
            return acc + Math.max(1, segment.durationMs)
        }

        return acc
    }, 0)
}
