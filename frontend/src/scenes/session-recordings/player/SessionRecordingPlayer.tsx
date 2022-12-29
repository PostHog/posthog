import './SessionRecordingPlayer.scss'
import { useEffect, useMemo, useRef } from 'react'
import { useActions, useValues } from 'kea'
import {
    ONE_FRAME_MS,
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from './sessionRecordingPlayerLogic'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { PlayerController } from 'scenes/session-recordings/player/PlayerController'
import { LemonDivider } from 'lib/components/LemonDivider'
import { PlayerInspector } from 'scenes/session-recordings/player/inspector/PlayerInspector'
import { PlayerMeta } from './PlayerMeta'
import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'
import clsx from 'clsx'
import { HotkeysInterface, useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { RecordingNotFound } from 'scenes/session-recordings/player/RecordingNotFound'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { SessionRecordingType } from '~/types'
import { PlayerFrameOverlay } from './PlayerFrameOverlay'

export function useFrameRef({
    sessionRecordingId,
    playerKey,
}: SessionRecordingPlayerLogicProps): React.MutableRefObject<HTMLDivElement | null> {
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

export interface SessionRecordingPlayerProps extends SessionRecordingPlayerLogicProps {
    includeMeta?: boolean
    noBorder?: boolean
    nextSessionRecording?: Partial<SessionRecordingType>
}

export const createPlaybackSpeedKey = (action: (val: number) => void): HotkeysInterface => {
    return PLAYBACK_SPEEDS.map((x, i) => ({ key: `${i}`, value: x })).reduce(
        (acc, x) => ({ ...acc, [x.key]: { action: () => action(x.value) } }),
        {}
    )
}

export function SessionRecordingPlayer(props: SessionRecordingPlayerProps): JSX.Element {
    const {
        sessionRecordingId,
        sessionRecordingData,
        playerKey,
        includeMeta = true,
        recordingStartTime, // While optional, including recordingStartTime allows the underlying ClickHouse query to be much faster
        matching,
        noBorder = false,
        nextSessionRecording,
    } = props

    const logicProps = {
        sessionRecordingId,
        playerKey,
        matching,
        sessionRecordingData,
        recordingStartTime,
    }
    const { setIsFullScreen, setPause, togglePlayPause, seekBackward, seekForward, setSpeed } = useActions(
        sessionRecordingPlayerLogic(logicProps)
    )
    const { isNotFound } = useValues(sessionRecordingDataLogic(logicProps))
    const { isFullScreen } = useValues(sessionRecordingPlayerLogic(logicProps))
    const frame = useFrameRef(logicProps)

    const speedHotkeys = useMemo(() => createPlaybackSpeedKey(setSpeed), [setSpeed])

    useKeyboardHotkeys(
        {
            f: {
                action: () => setIsFullScreen(!isFullScreen),
            },
            ' ': {
                action: () => togglePlayPause(),
            },
            arrowleft: {
                action: (e) => {
                    console.log(e)
                    if (e.ctrlKey || e.metaKey) {
                        return
                    }
                    e.preventDefault()
                    e.altKey && setPause()
                    seekBackward(e.altKey ? ONE_FRAME_MS : undefined)
                },
                willHandleEvent: true,
            },
            arrowright: {
                action: (e) => {
                    if (e.ctrlKey || e.metaKey) {
                        return
                    }
                    e.preventDefault()
                    e.altKey && setPause()
                    seekForward(e.altKey ? ONE_FRAME_MS : undefined)
                },
                willHandleEvent: true,
            },
            ...speedHotkeys,
            ...(isFullScreen ? { escape: { action: () => setIsFullScreen(false) } } : {}),
        },
        [isFullScreen]
    )

    usePageVisibility((pageIsVisible) => {
        if (!pageIsVisible) {
            setPause()
        }
    })

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        1000: 'medium',
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
            ref={ref}
            className={clsx('SessionRecordingPlayer', {
                'SessionRecordingPlayer--fullscreen': isFullScreen,
                'SessionRecordingPlayer--no-border': noBorder,
                'SessionRecordingPlayer--widescreen': !isFullScreen && size !== 'small',
            })}
        >
            <div className="SessionRecordingPlayer__main">
                {includeMeta || isFullScreen ? <PlayerMeta {...props} /> : null}
                <div className="SessionRecordingPlayer__body">
                    <PlayerFrame sessionRecordingId={sessionRecordingId} ref={frame} playerKey={playerKey} />
                    <PlayerFrameOverlay
                        sessionRecordingId={sessionRecordingId}
                        playerKey={playerKey}
                        nextSessionRecording={nextSessionRecording}
                    />
                </div>
                <LemonDivider className="my-0" />
                <PlayerController sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
            </div>
            {!isFullScreen && (
                <div className="SessionRecordingPlayer__inspector">
                    <PlayerInspector {...logicProps} />
                </div>
            )}
        </div>
    )
}
