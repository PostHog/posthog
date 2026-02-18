import { useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { ReplayInactivityPeriod } from '~/queries/schema/schema-general'
import { SessionPlayerState } from '~/types'

import { sessionRecordingDataCoordinatorLogic } from './sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

declare global {
    interface Window {
        // Track active/inactive periods to consume from backend later
        __POSTHOG_INACTIVITY_PERIODS__?: ReplayInactivityPeriod[]
        // Signal segment changes to backend (backend tracks actual video timestamps)
        __POSTHOG_CURRENT_SEGMENT_START_TS__?: number
        __POSTHOG_SEGMENT_COUNTER__?: number
    }
}

export function PlayerFrameMetaOverlay(): JSX.Element | null {
    const { logicProps, currentURL, currentPlayerTimeSeconds, currentSegment, endReached, currentPlayerState } =
        useValues(sessionRecordingPlayerLogic)

    // Load pre-processed segments
    const { segments: recordingSegments } = useValues(sessionRecordingDataCoordinatorLogic(logicProps))

    // Track when recording playback started (for VIDEO_T display)
    const recordingPlaybackStartTime = useRef<number | null>(null)
    // Track how much time passed since the first playback started (state for re-renders)
    const [timePassedSinceFirstPlayback, setTimePassedSinceFirstPlayback] = useState<number | null>(null)

    // Process all segments at once when available to fill data on all active/inactive periods
    useEffect(() => {
        // Reset segment tracking globals
        window.__POSTHOG_CURRENT_SEGMENT_START_TS__ = undefined
        window.__POSTHOG_SEGMENT_COUNTER__ = 0

        // If no segments available - no periods to track
        if (!recordingSegments || recordingSegments.length === 0) {
            window.__POSTHOG_INACTIVITY_PERIODS__ = []
            return
        }
        // Segments use Unix timestamps, so we need to use them also (instead of 0 as a start)
        const recordingStartTimestamp = recordingSegments[0].startTimestamp
        // Convert segments into inactivity periods metadata
        // Note: recording_ts_from_s will be added by the backend based on actual video time
        const periods: ReplayInactivityPeriod[] = recordingSegments
            // Skipping buffers, keeping windows and gaps
            .filter((segment) => segment.kind !== 'buffer' && segment.kind !== 'gap')
            .map((segment) => ({
                ts_from_s: (segment.startTimestamp - recordingStartTimestamp) / 1000,
                ts_to_s: (segment.endTimestamp - recordingStartTimestamp) / 1000,
                active: segment.isActive ?? true,
            }))
            // Ensure to keep only periods with >0 duration
            .filter((p) => p.ts_to_s > p.ts_from_s)
        // Store into the global variable to be used by the backend
        window.__POSTHOG_INACTIVITY_PERIODS__ = periods
    }, [recordingSegments])

    // Track when the first playback starts (for VIDEO_T display)
    useEffect(() => {
        if (currentPlayerState === SessionPlayerState.PLAY && recordingPlaybackStartTime.current === null) {
            recordingPlaybackStartTime.current = performance.now()
        }
    }, [currentPlayerState])

    // Update elapsed time display every second
    useEffect(() => {
        const interval = setInterval(() => {
            if (recordingPlaybackStartTime.current !== null) {
                setTimePassedSinceFirstPlayback((performance.now() - recordingPlaybackStartTime.current) / 1000)
            }
        }, 1000)
        return () => clearInterval(interval)
    }, [])

    // Signal segment changes to backend via globals
    // Backend will track actual video timestamps when these change
    useEffect(() => {
        if (!currentSegment || !recordingSegments?.length) {
            return
        }
        // Track only active segments (inactive segments are tracked via __POSTHOG_INACTIVITY_PERIODS__ above)
        if (!currentSegment.isActive) {
            return
        }
        // Calculate ts_from_s for this segment
        const recordingStartTimestamp = recordingSegments[0].startTimestamp
        const segmentTsFromS = (currentSegment.startTimestamp - recordingStartTimestamp) / 1000
        // Update globals to signal segment change to backend
        window.__POSTHOG_CURRENT_SEGMENT_START_TS__ = segmentTsFromS
        window.__POSTHOG_SEGMENT_COUNTER__ = (window.__POSTHOG_SEGMENT_COUNTER__ || 0) + 1
    }, [currentSegment, recordingSegments])

    // Skip rendering if no URL or player time is not available yet
    if (!currentURL || currentPlayerTimeSeconds === undefined) {
        return null
    }

    return (
        <div className="bg-black text-white text-md px-2 pt-1 pb-2 flex h-8 items-center justify-center gap-4 font-mono truncate">
            <span className="truncate">
                <span className="font-bold">URL:</span> {currentURL}
            </span>
            <span>
                <span className="font-bold">REC_T:</span> {currentPlayerTimeSeconds}
            </span>
            {timePassedSinceFirstPlayback !== null && (
                // TIP: Display for debugging
                <span style={{ display: 'none' }}>
                    <span className="font-bold">VIDEO_T:</span> {timePassedSinceFirstPlayback.toFixed(0)}
                </span>
            )}
            {endReached ? (
                <span className="font-bold text-green-400">[RECORDING ENDED]</span>
            ) : currentSegment?.isActive === false ? (
                <span className="font-bold text-yellow-400">[IDLE]</span>
            ) : null}
        </div>
    )
}
