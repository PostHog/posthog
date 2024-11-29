import './SessionRecordingPlayer.scss'

import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { BuilderHog2 } from 'lib/components/hedgehogs'
import { dayjs } from 'lib/dayjs'
import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import { HotkeysInterface, useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { useMemo, useRef } from 'react'
import { useNotebookDrag } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { RecordingNotFound } from 'scenes/session-recordings/player/RecordingNotFound'
import { MatchingEventsMatchType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'

import { NetworkView } from '../apm/NetworkView'
import { PlayerController } from './controller/PlayerController'
import { PlayerFrame } from './PlayerFrame'
import { PlayerFrameOverlay } from './PlayerFrameOverlay'
import { PlayerMeta } from './PlayerMeta'
import { PlaybackMode, playerSettingsLogic } from './playerSettingsLogic'
import { PlayerSidebar } from './PlayerSidebar'
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
    const playerMainRef = useRef<HTMLDivElement>(null)

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
    const { isNotFound, snapshotsInvalid, start } = useValues(sessionRecordingDataLogic(logicProps))
    const { loadSnapshots } = useActions(sessionRecordingDataLogic(logicProps))
    const { isFullScreen, explorerMode, isBuffering, messageTooLargeWarnings } = useValues(
        sessionRecordingPlayerLogic(logicProps)
    )
    const speedHotkeys = useMemo(() => createPlaybackSpeedKey(setSpeed), [setSpeed])
    const { isVerticallyStacked, sidebarOpen, playbackMode } = useValues(playerSettingsLogic)

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
            1050: 'medium',
            1500: 'wide',
        },
        {
            ref: playerRef,
        }
    )
    const { size: playerMainSize } = useResizeBreakpoints(
        {
            0: 'small',
            750: 'medium',
        },
        {
            ref: playerMainRef,
        }
    )

    const lessThanFiveMinutesOld = dayjs().diff(start, 'minute') <= 5
    const cannotPlayback = snapshotsInvalid && lessThanFiveMinutesOld && !messageTooLargeWarnings

    const { draggable, elementProps } = useNotebookDrag({ href: urls.replaySingle(sessionRecordingId) })

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
                className={clsx(
                    'SessionRecordingPlayer',
                    {
                        'SessionRecordingPlayer--fullscreen': isFullScreen,
                        'SessionRecordingPlayer--no-border': noBorder,
                        'SessionRecordingPlayer--buffering': isBuffering,
                        'SessionRecordingPlayer--stacked-vertically': sidebarOpen && isVerticallyStacked,
                    },
                    `SessionRecordingPlayer--${size}`
                )}
                onClick={incrementClickCount}
            >
                <FloatingContainerContext.Provider value={playerRef}>
                    {explorerMode ? (
                        <SessionRecordingPlayerExplorer {...explorerMode} onClose={() => closeExplorer()} />
                    ) : (
                        <>
                            <div
                                className="SessionRecordingPlayer__main flex flex-col h-full w-full"
                                ref={playerMainRef}
                            >
                                {cannotPlayback ? (
                                    <div className="flex flex-1 flex-col items-center justify-center">
                                        <BuilderHog2 height={200} />
                                        <h1>We're still working on it</h1>
                                        <p>
                                            This recording hasn't been fully ingested yet. It should be ready to watch
                                            in a few minutes.
                                        </p>
                                        <LemonButton type="secondary" onClick={loadSnapshots}>
                                            Reload
                                        </LemonButton>
                                    </div>
                                ) : (
                                    <div className="flex w-full h-full">
                                        <div className="flex flex-col flex-1 w-full">
                                            {playbackMode === PlaybackMode.Recording ? (
                                                <>
                                                    {!noMeta || isFullScreen ? (
                                                        <PlayerMeta iconsOnly={playerMainSize === 'small'} />
                                                    ) : null}

                                                    <div
                                                        className="SessionRecordingPlayer__body"
                                                        draggable={draggable}
                                                        {...elementProps}
                                                    >
                                                        <PlayerFrame />
                                                        <PlayerFrameOverlay />
                                                    </div>
                                                    <PlayerController />
                                                </>
                                            ) : (
                                                <NetworkView sessionRecordingId={sessionRecordingId} />
                                            )}
                                        </div>
                                    </div>
                                )}
                            </div>

                            {!noInspector && <PlayerSidebar />}
                        </>
                    )}
                </FloatingContainerContext.Provider>
            </div>
        </BindLogic>
    )
}
