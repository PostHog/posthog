import { useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

interface InactivityPeriod {
    ts_from_s: number
    ts_to_s?: number
    active: boolean
}

declare global {
    // Track active/inactive periods to consume from backend later
    interface Window {
        __POSTHOG_INACTIVITY_PERIODS__?: InactivityPeriod[]
    }
}

export function PlayerFrameMetaOverlay(): JSX.Element | null {
    const { currentURL, currentPlayerTime, currentSegment } = useValues(sessionRecordingPlayerLogic)

    const [inactivityPeriods, setInactivityPeriods] = useState<InactivityPeriod[]>([])
    const prevIsActiveRef = useRef<boolean | undefined>(undefined)
    const initializedRef = useRef(false)

    const currentTimeSeconds = currentPlayerTime !== undefined ? Math.floor(currentPlayerTime / 1000) : undefined
    const currentIsActive = currentSegment?.isActive

    useEffect(() => {
        // Nothing to track yet
        if (currentTimeSeconds === undefined || currentIsActive === undefined) {
            return
        }
        // Initialize first entry
        if (!initializedRef.current) {
            initializedRef.current = true
            prevIsActiveRef.current = currentIsActive
            setInactivityPeriods([{ ts_from_s: currentTimeSeconds, active: currentIsActive }])
            return
        }
        // Detect status change
        if (prevIsActiveRef.current !== currentIsActive) {
            setInactivityPeriods((prev) => {
                const updated = [...prev]
                // Finish the previous period
                if (updated.length > 0) {
                    updated[updated.length - 1].ts_to_s = currentTimeSeconds
                }
                // Start a new period
                updated.push({ ts_from_s: currentTimeSeconds, active: currentIsActive })
                return updated
            })
            prevIsActiveRef.current = currentIsActive
        }
    }, [currentTimeSeconds, currentIsActive])

    // Expose to global variable for video exporter, filtering out zero-duration periods
    useEffect(() => {
        window.__POSTHOG_INACTIVITY_PERIODS__ = inactivityPeriods.filter(
            (p) => p.ts_to_s === undefined || p.ts_to_s > p.ts_from_s
        )
    }, [inactivityPeriods])

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
