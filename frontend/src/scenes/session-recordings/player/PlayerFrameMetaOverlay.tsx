import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { ReplayInactivityPeriod } from '~/queries/schema/schema-general'
import { SessionPlayerState } from '~/types'

import { sessionRecordingDataCoordinatorLogic } from './sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

declare global {
    // Track active/inactive periods to consume from backend later
    interface Window {
        __POSTHOG_INACTIVITY_PERIODS__?: ReplayInactivityPeriod[]
    }
}

export function PlayerFrameMetaOverlay(): JSX.Element | null {
    const { logicProps, currentURL, currentPlayerTimeSeconds, currentSegment, endReached, currentPlayerState } =
        useValues(sessionRecordingPlayerLogic)

    // Load pre-processed segments
    const { segments: recordingSegments } = useValues(sessionRecordingDataCoordinatorLogic(logicProps))

    // Track when recording playback started
    const recordingPlaybackStartTime = useRef<number | null>(null)
    // Track which segments we've already processed to avoid duplicates
    const processedSegmentTimestamps = useRef<Set<number>>(new Set())

    // Process all segments at once when available to fill data on all active/inactive periods
    useEffect(() => {
        // If no segments available - no periods to track
        if (!recordingSegments || recordingSegments.length === 0) {
            window.__POSTHOG_INACTIVITY_PERIODS__ = []
            return
        }
        // Segments use Unix timestamps, so we need to use them also (instead of 0 as a start)
        const recordingStartTimestamp = recordingSegments[0].startTimestamp
        // Convert segments into inactivity periods metadata
        const periods: ReplayInactivityPeriod[] = recordingSegments
            // Skipping buffers, keeping windows and gaps
            .filter((segment) => segment.kind !== 'buffer')
            .map((segment) => ({
                ts_from_s: Math.floor((segment.startTimestamp - recordingStartTimestamp) / 1000),
                ts_to_s: Math.floor((segment.endTimestamp - recordingStartTimestamp) / 1000),
                active: segment.isActive ?? true,
            }))
            // Ensure to keep only periods with >0 duration
            .filter((p) => p.ts_to_s > p.ts_from_s)
        // Ensure the first period starts at video time 0
        if (periods?.[0]) {
            periods[0].recording_ts_from_s = 0
        }
        // Store into the global variable to be used by the backend
        window.__POSTHOG_INACTIVITY_PERIODS__ = periods
    }, [recordingSegments])

    // Track when the first playback starts to get the starting point
    useEffect(() => {
        if (currentPlayerState === SessionPlayerState.PLAY && recordingPlaybackStartTime.current === null) {
            recordingPlaybackStartTime.current = performance.now()
        }
    }, [currentPlayerState])

    // Update period's recording_ts_from_s when segment changes
    useEffect(() => {
        // Skip if no segments available
        if (!currentSegment || !recordingSegments?.length || recordingPlaybackStartTime.current === null) {
            return
        }
        // Skip buffers
        if (currentSegment.kind === 'buffer') {
            return
        }
        // Skip if already processed this segment
        // Assuming that each segment has its unique start timestamp
        if (processedSegmentTimestamps.current.has(currentSegment.startTimestamp)) {
            return
        }
        // Calculate the starting ts to match segments
        const recordingStartTimestamp = recordingSegments[0].startTimestamp
        const segmentTsFromS = Math.floor((currentSegment.startTimestamp - recordingStartTimestamp) / 1000)
        // Calculate how much time has passed since the first playback started
        const recordingTsFromS = Math.floor((performance.now() - recordingPlaybackStartTime.current) / 1000)
        // Find and update the corresponding period
        const periods = window.__POSTHOG_INACTIVITY_PERIODS__ || []
        const updatedPeriods = periods.map((period) => {
            if (period.ts_from_s === segmentTsFromS) {
                return { ...period, recording_ts_from_s: recordingTsFromS }
            }
            return period
        })
        // Store into the global variable to be used by the backend
        window.__POSTHOG_INACTIVITY_PERIODS__ = updatedPeriods
        processedSegmentTimestamps.current.add(currentSegment.startTimestamp)
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
            {/* Using shorter message to allow more space for the URL */}
            {endReached ? (
                <span className="font-bold text-green-400">[RECORDING ENDED]</span>
            ) : currentSegment?.isActive === false ? (
                <span className="font-bold text-yellow-400">[IDLE]</span>
            ) : null}
        </div>
    )
}
