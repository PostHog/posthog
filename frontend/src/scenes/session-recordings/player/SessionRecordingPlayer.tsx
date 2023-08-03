import './SessionRecordingPlayer.scss'
import { useMemo, useRef, useState } from 'react'
import { BindLogic, useActions, useValues } from 'kea'
import {
    ONE_FRAME_MS,
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
    SessionRecordingPlayerMode,
} from './sessionRecordingPlayerLogic'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { PlayerController } from 'scenes/session-recordings/player/controller/PlayerController'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { PlayerInspector } from 'scenes/session-recordings/player/inspector/PlayerInspector'
import { PlayerMeta } from './PlayerMeta'
import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'
import clsx from 'clsx'
import { HotkeysInterface, useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { RecordingNotFound } from 'scenes/session-recordings/player/RecordingNotFound'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { PlayerFrameOverlay } from './PlayerFrameOverlay'
import { SessionRecordingPlayerExplorer } from './view-explorer/SessionRecordingPlayerExplorer'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { urls } from 'scenes/urls'
import { MatchingEventsMatchType } from 'scenes/session-recordings/playlist/sessionRecordingsListLogic'

export interface SessionRecordingPlayerProps extends SessionRecordingPlayerLogicProps {
    noMeta?: boolean
    noBorder?: boolean
    noInspector?: boolean
    matchingEventsMatchType?: MatchingEventsMatchType
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
        noMeta = false,
        recordingStartTime, // While optional, including recordingStartTime allows the underlying ClickHouse query to be much faster
        matching,
        matchingEventsMatchType,
        noBorder = false,
        noInspector = false,
        autoPlay = true,
        nextSessionRecording,
        mode = SessionRecordingPlayerMode.Standard,
    } = props

    const playerRef = useRef<HTMLDivElement>(null)

    const logicProps: SessionRecordingPlayerLogicProps = {
        sessionRecordingId,
        playerKey,
        matching,
        matchingEventsMatchType,
        sessionRecordingData,
        recordingStartTime,
        autoPlay,
        nextSessionRecording,
        mode,
        playerRef,
    }
    const {
        incrementClickCount,
        setIsFullScreen,
        setPause,
        togglePlayPause,
        seekBackward,
        seekForward,
        setSpeed,
        closeExplorer,
    } = useActions(sessionRecordingPlayerLogic(logicProps))
    const { isNotFound } = useValues(sessionRecordingDataLogic(logicProps))
    const { isFullScreen, explorerMode } = useValues(sessionRecordingPlayerLogic(logicProps))
    const speedHotkeys = useMemo(() => createPlaybackSpeedKey(setSpeed), [setSpeed])

    useKeyboardHotkeys(
        {
            f: {
                action: () => setIsFullScreen(!isFullScreen),
            },
            space: {
                action: () => togglePlayPause(),
            },
            arrowleft: {
                action: (e) => {
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

    const { size } = useResizeBreakpoints(
        {
            0: 'small',
            1000: 'medium',
        },
        playerRef
    )

    const [inspectorFocus, setInspectorFocus] = useState(false)

    if (isNotFound) {
        return (
            <div className="text-center">
                <RecordingNotFound />
            </div>
        )
    }

    return (
        <BindLogic logic={sessionRecordingPlayerLogic} props={logicProps}>
            <div
                ref={playerRef}
                className={clsx('SessionRecordingPlayer', {
                    'SessionRecordingPlayer--fullscreen': isFullScreen,
                    'SessionRecordingPlayer--no-border': noBorder,
                    'SessionRecordingPlayer--widescreen': !isFullScreen && size !== 'small',
                    'SessionRecordingPlayer--inspector-focus': inspectorFocus,
                    'SessionRecordingPlayer--inspector-hidden': noInspector,
                })}
                onClick={incrementClickCount}
            >
                {explorerMode ? (
                    <SessionRecordingPlayerExplorer {...explorerMode} onClose={() => closeExplorer()} />
                ) : (
                    <>
                        <div className="SessionRecordingPlayer__main">
                            {!noMeta || isFullScreen ? <PlayerMeta /> : null}
                            <div className="SessionRecordingPlayer__body">
                                <PlayerFrame />
                                <PlayerFrameOverlay />
                            </div>
                            <LemonDivider className="my-0" />
                            <PlayerController />
                        </div>
                        {!noInspector && <PlayerInspector onFocusChange={setInspectorFocus} />}
                    </>
                )}
            </div>
        </BindLogic>
    )
}
