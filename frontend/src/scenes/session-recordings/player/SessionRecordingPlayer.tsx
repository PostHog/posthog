import './SessionRecordingPlayer.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import { HotkeysInterface, useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNotebookDrag } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { PlayerController } from 'scenes/session-recordings/player/controller/PlayerController'
import { PlayerInspector } from 'scenes/session-recordings/player/inspector/PlayerInspector'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { RecordingNotFound } from 'scenes/session-recordings/player/RecordingNotFound'
import { MatchingEventsMatchType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'

import { PlayerFrameOverlay } from './PlayerFrameOverlay'
import { PlayerMeta } from './PlayerMeta'
import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'
import {
    ONE_FRAME_MS,
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
    SessionRecordingPlayerMode,
} from './sessionRecordingPlayerLogic'
import { SessionRecordingPlayerExplorer } from './view-explorer/SessionRecordingPlayerExplorer'

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
        matchingEventsMatchType,
        noBorder = false,
        noInspector = false,
        autoPlay = true,
        playlistLogic,
        mode = SessionRecordingPlayerMode.Standard,
        pinned,
        setPinned,
    } = props

    const playerRef = useRef<HTMLDivElement>(null)

    const logicProps: SessionRecordingPlayerLogicProps = {
        sessionRecordingId,
        playerKey,
        matchingEventsMatchType,
        sessionRecordingData,
        autoPlay,
        playlistLogic,
        mode,
        playerRef,
        pinned,
        setPinned,
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
    const { isFullScreen, explorerMode, isBuffering } = useValues(sessionRecordingPlayerLogic(logicProps))
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
            0: 'tiny',
            400: 'small',
            1000: 'medium',
        },
        {
            ref: playerRef,
        }
    )

    const isWidescreen = !isFullScreen && size === 'medium'

    const [inspectorExpanded, setInspectorExpanded] = useState(isWidescreen)

    const { draggable, elementProps } = useNotebookDrag({ href: urls.replaySingle(sessionRecordingId) })

    useEffect(() => {
        if (isWidescreen) {
            setInspectorExpanded(true)
        }
    }, [isWidescreen])

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
                    'SessionRecordingPlayer--widescreen': isWidescreen,
                    'SessionRecordingPlayer--inspector-focus': inspectorExpanded || isWidescreen,
                    'SessionRecordingPlayer--inspector-hidden': noInspector || size === 'tiny',
                    'SessionRecordingPlayer--buffering': isBuffering,
                })}
                onClick={incrementClickCount}
            >
                <FloatingContainerContext.Provider value={playerRef}>
                    {explorerMode ? (
                        <SessionRecordingPlayerExplorer {...explorerMode} onClose={() => closeExplorer()} />
                    ) : (
                        <>
                            <div
                                className="SessionRecordingPlayer__main"
                                onClick={() => {
                                    if (!isWidescreen) {
                                        setInspectorExpanded(false)
                                    }
                                }}
                            >
                                {(!noMeta || isFullScreen) && size !== 'tiny' ? <PlayerMeta /> : null}

                                <div className="SessionRecordingPlayer__body" draggable={draggable} {...elementProps}>
                                    <PlayerFrame />
                                    <PlayerFrameOverlay />
                                </div>
                                <LemonDivider className="my-0" />
                                <PlayerController />
                            </div>
                            {!noInspector && (
                                <PlayerInspector
                                    inspectorExpanded={inspectorExpanded}
                                    setInspectorExpanded={setInspectorExpanded}
                                />
                            )}
                        </>
                    )}
                </FloatingContainerContext.Provider>
            </div>
        </BindLogic>
    )
}
