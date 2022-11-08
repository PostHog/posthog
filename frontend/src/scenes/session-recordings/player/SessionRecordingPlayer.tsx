import './SessionRecordingPlayer.scss'
import { useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { PlayerController } from 'scenes/session-recordings/player/PlayerController'
import { LemonDivider } from 'lib/components/LemonDivider'
import { PlayerInspector } from 'scenes/session-recordings/player/PlayerInspector'
import { PlayerFilter } from 'scenes/session-recordings/player/list/PlayerFilter'
import { SessionRecordingPlayerProps } from '~/types'
import { PlayerMeta } from './PlayerMeta'
import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'
import clsx from 'clsx'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { RecordingNotFound } from 'scenes/session-recordings/player/RecordingNotFound'
import { urls } from 'scenes/urls'

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

export function SessionRecordingPlayer({
    sessionRecordingId,
    playerKey,
    includeMeta = true,
    recordingStartTime, // While optional, including recordingStartTime allows the underlying ClickHouse query to be much faster
    matching,
    isDetail = false, // True if player is shown in separate detail page
}: SessionRecordingPlayerProps): JSX.Element {
    const { handleKeyDown, setIsFullScreen, setPause } = useActions(
        sessionRecordingPlayerLogic({ sessionRecordingId, playerKey, recordingStartTime, matching })
    )
    const { isNotFound } = useValues(sessionRecordingDataLogic({ sessionRecordingId, recordingStartTime }))
    const { isFullScreen } = useValues(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const frame = useFrameRef({ sessionRecordingId, playerKey })

    useKeyboardHotkeys(
        {
            f: {
                action: () => setIsFullScreen(!isFullScreen),
            },
            ...(isFullScreen ? { escape: { action: () => setIsFullScreen(false) } } : {}),
            ...(!isDetail ? { d: { action: () => open(urls.sessionRecording(sessionRecordingId), '_blank') } } : {}),
        },
        [isFullScreen]
    )

    usePageVisibility((pageIsVisible) => {
        if (!pageIsVisible) {
            setPause()
        }
    })

    if (isNotFound) {
        return (
            <div className="text-center">
                <RecordingNotFound />
            </div>
        )
    }

    return (
        <div
            className={clsx('SessionRecordingPlayer', { 'SessionRecordingPlayer--fullscreen': isFullScreen })}
            onKeyDown={handleKeyDown}
        >
            {includeMeta || isFullScreen ? (
                <PlayerMeta sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
            ) : null}
            <div className="SessionRecordingPlayer__body">
                <PlayerFrame sessionRecordingId={sessionRecordingId} ref={frame} playerKey={playerKey} />
            </div>
            <LemonDivider className="my-0" />
            <PlayerController sessionRecordingId={sessionRecordingId} playerKey={playerKey} isDetail={isDetail} />
            {!isFullScreen && (
                <>
                    <LemonDivider className="my-0" />
                    <PlayerFilter sessionRecordingId={sessionRecordingId} playerKey={playerKey} matching={matching} />
                    <LemonDivider className="my-0" />
                    <PlayerInspector sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
                </>
            )}
        </div>
    )
}
