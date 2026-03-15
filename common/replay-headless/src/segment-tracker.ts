import type { RecordingSegment } from '@posthog/replay-shared'

import type { InactivityPeriod, PlayerConfig, PlayerError } from './types'

declare global {
    interface Window {
        __POSTHOG_PLAYER_CONFIG__?: PlayerConfig
        __POSTHOG_PLAYER_ERROR__?: PlayerError
        __POSTHOG_INACTIVITY_PERIODS__?: InactivityPeriod[]
        __POSTHOG_SEGMENT_COUNTER__?: number
        __POSTHOG_CURRENT_SEGMENT_START_TS__?: number
        __POSTHOG_RECORDING_STARTED__?: boolean
        __POSTHOG_RECORDING_ENDED__?: boolean
        __POSTHOG_RESOLUTION__?: { width: number; height: number }
    }
}

export function publishSegments(segments: RecordingSegment[], firstTimestamp: number): void {
    window.__POSTHOG_INACTIVITY_PERIODS__ = segments.map((seg) => ({
        ts_from_s: Math.round(seg.startTimestamp - firstTimestamp) / 1000,
        ts_to_s: Math.round(seg.endTimestamp - firstTimestamp) / 1000,
        active: seg.isActive,
    }))
    window.__POSTHOG_SEGMENT_COUNTER__ = 0
}

export function createSegmentTracker(
    segments: RecordingSegment[],
    firstTimestamp: number
): (timestamp: number) => void {
    let currentSegmentIndex = -1

    return (timestamp: number): void => {
        for (let i = 0; i < segments.length; i++) {
            if (timestamp >= segments[i].startTimestamp && timestamp <= segments[i].endTimestamp) {
                if (i !== currentSegmentIndex) {
                    currentSegmentIndex = i
                    window.__POSTHOG_SEGMENT_COUNTER__ = (window.__POSTHOG_SEGMENT_COUNTER__ || 0) + 1
                    window.__POSTHOG_CURRENT_SEGMENT_START_TS__ =
                        Math.round(segments[i].startTimestamp - firstTimestamp) / 1000
                }
                return
            }
        }
    }
}

export function signalRecordingStarted(): void {
    window.__POSTHOG_RECORDING_STARTED__ = true
}

export function signalRecordingEnded(): void {
    window.__POSTHOG_RECORDING_ENDED__ = true
}
