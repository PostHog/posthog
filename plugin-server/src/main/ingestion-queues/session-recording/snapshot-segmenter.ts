/**
 * This file is a cut-down version of the segmenter.ts
 * https://github.com/PostHog/posthog/blob/db2deaf650d2eca9addba5e3f304a17a21041f25/frontend/src/scenes/session-recordings/player/utils/segmenter.ts
 *
 * It has been modified to not need the same dependencies
 * Any changes may need to be sync'd between the two
 */

import { RRWebEvent } from '../../../types'

const activeSources = [1, 2, 3, 4, 5, 6, 7, 12]

const ACTIVITY_THRESHOLD_MS = 5000

export interface RRWebPartialData {
    href?: string
    source?: number
    payload?: Record<string, any>
    plugin?: string
}

interface RecordingSegment {
    kind: 'window' | 'buffer' | 'gap'
    startTimestamp: number // Epoch time that the segment starts
    endTimestamp: number // Epoch time that the segment ends
    durationMs: number
    isActive: boolean
}

const isActiveEvent = (event: RRWebEvent): boolean => {
    return event.type === 3 && activeSources.includes(event.data?.source || -1)
}

const createSegments = (snapshots: RRWebEvent[]): RecordingSegment[] => {
    let segments: RecordingSegment[] = []
    let activeSegment!: Partial<RecordingSegment>
    let lastActiveEventTimestamp = 0

    snapshots.forEach((snapshot) => {
        const eventIsActive = isActiveEvent(snapshot)

        // When do we create a new segment?
        // 1. If we don't have one yet
        let isNewSegment = !activeSegment

        // 2. If it is currently inactive but a new "active" event comes in
        if (eventIsActive && !activeSegment?.isActive) {
            isNewSegment = true
        }

        // 3. If it is currently active but no new active event has been seen for the activity threshold
        if (activeSegment?.isActive && lastActiveEventTimestamp + ACTIVITY_THRESHOLD_MS < snapshot.timestamp) {
            isNewSegment = true
        }

        // NOTE: We have to make sure that we set this _after_ we use it
        lastActiveEventTimestamp = eventIsActive ? snapshot.timestamp : lastActiveEventTimestamp

        if (isNewSegment) {
            if (activeSegment) {
                segments.push(activeSegment as RecordingSegment)
            }

            activeSegment = {
                kind: 'window',
                startTimestamp: snapshot.timestamp,
                isActive: eventIsActive,
            }
        }

        activeSegment.endTimestamp = snapshot.timestamp
    })

    if (activeSegment) {
        segments.push(activeSegment as RecordingSegment)
    }

    segments = segments.map((segment) => {
        // These can all be done in a loop at the end...
        segment.durationMs = segment.endTimestamp - segment.startTimestamp
        return segment
    })

    return segments
}

/**
 * TODO add code sharing between plugin-server and front-end so that this method can
 * call the same createSegments function as the front-end
 */
export const activeMilliseconds = (snapshots: RRWebEvent[]): number => {
    const segments = createSegments(snapshots)
    return segments.reduce((acc, segment) => {
        if (segment.isActive) {
            // if the segment is active but has no duration we count it as 1ms
            // to distinguish it from segments with no activity at all
            return acc + Math.max(1, segment.durationMs)
        }

        return acc
    }, 0)
}
