import { useValues } from 'kea'
import { useEffect } from 'react'

import { ReplayInactivityPeriod } from '~/queries/schema/schema-general'

import { sessionRecordingDataCoordinatorLogic } from './sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

declare global {
    // Track active/inactive periods to consume from backend later
    interface Window {
        __POSTHOG_INACTIVITY_PERIODS__?: ReplayInactivityPeriod[]
    }
}

export function PlayerFrameMetaOverlay(): JSX.Element | null {
    const { logicProps, currentURL, currentPlayerTime, currentSegment } = useValues(sessionRecordingPlayerLogic)

    // Load pre-processed segments
    const { segments: recordingSegments } = useValues(sessionRecordingDataCoordinatorLogic(logicProps))

    // Process all segments at once when available
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

        window.__POSTHOG_INACTIVITY_PERIODS__ = periods
    }, [recordingSegments])

    if (!currentURL || currentPlayerTime === undefined) {
        return null
    }

    const isInactive = currentSegment?.isActive === false

    return (
        <div className="bg-black text-white text-md px-2 pt-1 pb-2 flex justify-center gap-4 font-mono truncate">
            <span className="truncate">
                <span className="font-bold">URL:</span> {currentURL}
            </span>
            <span>
                <span className="font-bold">REC_T:</span> {Math.floor(currentPlayerTime / 1000)}
            </span>
            {isInactive && (
                <span>
                    <span className="font-bold text-yellow-400">[IDLE]</span>
                </span>
            )}
        </div>
    )
}
