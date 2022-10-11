import React, { useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { SessionRecordingPlayerProps } from '~/types'
import { sessionRecordingPlayerLogic } from '../player/sessionRecordingPlayerLogic'
import { sessionRecordingDataLogic } from '../player/sessionRecordingDataLogic'

export function useFrameRef({
    sessionRecordingId,
    playerKey,
}: SessionRecordingPlayerProps): React.MutableRefObject<HTMLDivElement | null> {
    const { setRootFrame } = useActions(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const frame = useRef<HTMLDivElement | null>(null)
    // Need useEffect to populate replayer on component paint
    useEffect(() => {
        if (frame.current) {
            setRootFrame(frame.current)
        }
    }, [frame, sessionRecordingId])

    return frame
}

export function SessionRecordingPreview({
    sessionRecordingId,
    playerKey,
    recordingStartTime, // While optional, including recordingStartTime allows the underlying ClickHouse query to be much faster
}: SessionRecordingPlayerProps): JSX.Element {
    const { sessionPlayerData } = useValues(sessionRecordingDataLogic({ sessionRecordingId, recordingStartTime }))
    const frame = useFrameRef({ sessionRecordingId, playerKey })

    console.log({ sessionPlayerData })

    return (
        <div className="SessionRecordingPreview h-20" tabIndex={0}>
            <PlayerFrame sessionRecordingId={sessionRecordingId} ref={frame} playerKey={playerKey} />
        </div>
    )
}
