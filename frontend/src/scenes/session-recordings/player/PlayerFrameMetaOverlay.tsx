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

    const { segments: recordingSegments } = useValues(sessionRecordingDataCoordinatorLogic(logicProps))

    const recordingPlaybackStartTime = useRef<number | null>(null)
    const [timePassedSinceFirstPlayback, setTimePassedSinceFirstPlayback] = useState<number | null>(null)

    useEffect(() => {
        window.__POSTHOG_CURRENT_SEGMENT_START_TS__ = undefined
        window.__POSTHOG_SEGMENT_COUNTER__ = 0

        if (!recordingSegments || recordingSegments.length === 0) {
            window.__POSTHOG_INACTIVITY_PERIODS__ = []
            return
        }
        // Segments carry Unix timestamps, so each period is relative to the first segment instead of to 0
        const recordingStartTimestamp = recordingSegments[0].startTimestamp
        // The backend adds recording_ts_from_s to each period from the actual video time
        const periods: ReplayInactivityPeriod[] = recordingSegments
            .filter((segment) => segment.kind !== 'buffer' && segment.kind !== 'gap')
            .map((segment) => ({
                ts_from_s: (segment.startTimestamp - recordingStartTimestamp) / 1000,
                ts_to_s: (segment.endTimestamp - recordingStartTimestamp) / 1000,
                active: segment.isActive ?? true,
            }))
            .filter((p) => p.ts_to_s > p.ts_from_s)
        window.__POSTHOG_INACTIVITY_PERIODS__ = periods
    }, [recordingSegments])

    useEffect(() => {
        if (currentPlayerState === SessionPlayerState.PLAY && recordingPlaybackStartTime.current === null) {
            recordingPlaybackStartTime.current = performance.now()
        }
    }, [currentPlayerState])

    useEffect(() => {
        const interval = setInterval(() => {
            if (recordingPlaybackStartTime.current !== null) {
                setTimePassedSinceFirstPlayback((performance.now() - recordingPlaybackStartTime.current) / 1000)
            }
        }, 1000)
        return () => clearInterval(interval)
    }, [])

    useEffect(() => {
        if (!currentSegment || !recordingSegments?.length) {
            return
        }
        // Only active segments use these globals, because __POSTHOG_INACTIVITY_PERIODS__ carries the inactive ones
        if (!currentSegment.isActive) {
            return
        }
        const recordingStartTimestamp = recordingSegments[0].startTimestamp
        const segmentTsFromS = (currentSegment.startTimestamp - recordingStartTimestamp) / 1000
        window.__POSTHOG_CURRENT_SEGMENT_START_TS__ = segmentTsFromS
        window.__POSTHOG_SEGMENT_COUNTER__ = (window.__POSTHOG_SEGMENT_COUNTER__ || 0) + 1
    }, [currentSegment, recordingSegments])

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
                // Hidden by default, unhide it to debug video timing
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
