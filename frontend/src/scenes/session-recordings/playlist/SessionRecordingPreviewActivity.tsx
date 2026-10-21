import { useValues } from 'kea'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { activityAreaPath } from 'scenes/session-recordings/player/controller/activityCurvePath'
import {
    SessionRecordingPlayerLogicProps,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { SessionRecordingType } from '~/types'

import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { usePlayerMounted } from './usePlayerMounted'

const MAX_CURVE_POINTS = 120
const CURVE_HEIGHT = 100

/** Activity over time for the open recording, drawn from what the player has loaded; clicking the curve seeks there. */
export function SessionRecordingPreviewActivity({
    recording,
}: {
    recording: SessionRecordingType
}): JSX.Element | null {
    const { logicProps } = useValues(sessionRecordingsPlaylistLogic)
    const playerLogicProps: SessionRecordingPlayerLogicProps = {
        playerKey: logicProps.logicKey ?? 'playlist',
        sessionRecordingId: recording.id,
    }
    if (usePlayerMounted(playerLogicProps) !== 'mounted') {
        return null
    }
    return <ActivityCurve playerLogicProps={playerLogicProps} />
}

function ActivityCurve({
    playerLogicProps,
}: {
    playerLogicProps: SessionRecordingPlayerLogicProps
}): JSX.Element | null {
    const { activityPerSecond } = useValues(sessionRecordingPlayerLogic(playerLogicProps))
    const { smoothedPoints, maxY, durationSeconds } = activityPerSecond
    if (maxY <= 0 || durationSeconds <= 0) {
        return null
    }

    // One point per second would be thousands of path segments on a long recording; sample the peak of each bucket.
    const pointCount = Math.min(MAX_CURVE_POINTS, Math.ceil(durationSeconds))
    const secondsPerPoint = durationSeconds / pointCount
    const points = Array.from({ length: pointCount + 1 }, (_, i) => {
        const from = Math.floor(i * secondsPerPoint)
        const to = Math.floor((i + 1) * secondsPerPoint)
        let peak = 0
        for (let second = from; second <= to; second++) {
            peak = Math.max(peak, smoothedPoints[second]?.y ?? 0)
        }
        return {
            x: (i / pointCount) * MAX_CURVE_POINTS,
            y: CURVE_HEIGHT - (Math.log(peak + 1) / Math.log(maxY + 1)) * CURVE_HEIGHT,
        }
    })

    return (
        <Tooltip title="Click to jump to that point in the recording" placement="bottom">
            <button
                type="button"
                className="block w-full h-5 mt-1 text-muted hover:text-primary cursor-pointer"
                aria-label="Activity over time. Click to jump to that point in the recording."
                data-attr="playlist-row-activity"
                onClick={(e) => {
                    e.stopPropagation()
                    const { left, width } = e.currentTarget.getBoundingClientRect()
                    const fraction = Math.min(Math.max((e.clientX - left) / width, 0), 1)
                    sessionRecordingPlayerLogic
                        .findMounted(playerLogicProps)
                        ?.actions.seekToTime(fraction * durationSeconds * 1000)
                }}
            >
                <svg
                    viewBox={`0 0 ${MAX_CURVE_POINTS} ${CURVE_HEIGHT}`}
                    preserveAspectRatio="none"
                    className="w-full h-full"
                    aria-hidden="true"
                >
                    <path d={activityAreaPath(points, MAX_CURVE_POINTS, CURVE_HEIGHT, true)} fill="currentColor" />
                </svg>
            </button>
        </Tooltip>
    )
}
