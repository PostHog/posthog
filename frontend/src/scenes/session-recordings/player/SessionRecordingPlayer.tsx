import './styles.scss'
import React, { useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { PlayerControllerV3 } from 'scenes/session-recordings/player/PlayerController'
import { LemonDivider } from 'lib/components/LemonDivider'
import { PlayerInspectorV3 } from 'scenes/session-recordings/player/PlayerInspector'
import { PlayerFilter } from 'scenes/session-recordings/player/list/PlayerFilter'
import { SessionRecordingPlayerProps } from '~/types'
import { PlayerMetaV3 } from './PlayerMeta'
import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'
import { NotFound } from 'lib/components/NotFound'
import { Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import clsx from 'clsx'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'

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

export function SessionRecordingPlayerV3({
    sessionRecordingId,
    playerKey,
    includeMeta = true,
    recordingStartTime, // While optional, including recordingStartTime allows the underlying ClickHouse query to be much faster
    matching,
}: SessionRecordingPlayerProps): JSX.Element {
    const { handleKeyDown, setFullScreen } = useActions(
        sessionRecordingPlayerLogic({ sessionRecordingId, playerKey, recordingStartTime, matching })
    )
    const { isNotFound } = useValues(sessionRecordingDataLogic({ sessionRecordingId, recordingStartTime }))
    const { isFullScreen } = useValues(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const frame = useFrameRef({ sessionRecordingId, playerKey })

    useKeyboardHotkeys(
        {
            f: {
                action: () => setFullScreen(!isFullScreen),
            },
            ...(isFullScreen ? { escape: { action: () => setFullScreen(false) } } : {}),
        },
        [isFullScreen]
    )

    if (isNotFound) {
        return (
            <div className="text-center">
                <NotFound
                    object={'Recording'}
                    caption={
                        <>
                            The requested recording doesn't seem to exist. The recording may still be processing,
                            deleted due to age or have not been enabled. Please check your{' '}
                            <Link to={urls.projectSettings()}>project settings</Link> that recordings is turned on and
                            enabled for the domain in question.
                        </>
                    }
                />
            </div>
        )
    }

    return (
        <div
            className={clsx('SessionPlayerV3', { 'SessionPlayerV3--fullscreen': isFullScreen })}
            onKeyDown={handleKeyDown}
            tabIndex={0}
        >
            {includeMeta || isFullScreen ? (
                <PlayerMetaV3 sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
            ) : null}
            <div className="session-player-body flex">
                <div className="player-container ph-no-capture">
                    <PlayerFrame sessionRecordingId={sessionRecordingId} ref={frame} playerKey={playerKey} />
                </div>
            </div>
            <LemonDivider className="my-0" />
            <PlayerControllerV3 sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
            {!isFullScreen && (
                <>
                    <LemonDivider className="my-0" />
                    <PlayerFilter sessionRecordingId={sessionRecordingId} playerKey={playerKey} matching={matching} />
                    <LemonDivider className="my-0" />
                    <PlayerInspectorV3 sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
                </>
            )}
        </div>
    )
}
