import './SessionRecordingPlayer.scss'

import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'

import { BuilderHog2, SleepingHog } from 'lib/components/hedgehogs'
import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import { HotkeysInterface, useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { usePageVisibilityCb } from 'lib/hooks/usePageVisibility'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import posthog from 'posthog-js'
import { useEffect, useMemo, useRef } from 'react'
import { useNotebookDrag } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { PlayerFrameCommentOverlay } from 'scenes/session-recordings/player/commenting/PlayerFrameCommentOverlay'
import { RecordingNotFound } from 'scenes/session-recordings/player/RecordingNotFound'
import { MatchingEventsMatchType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'

import { PlayerController } from './controller/PlayerController'
import { PlayerMeta } from './player-meta/PlayerMeta'
import { PlayerFrame } from './PlayerFrame'
import { PlayerFrameOverlay } from './PlayerFrameOverlay'
import { playerSettingsLogic } from './playerSettingsLogic'
import { PlayerSidebar } from './PlayerSidebar'
import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'
import { SessionRecordingNextConfirmation } from './SessionRecordingNextConfirmation'
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
        (acc, x) => Object.assign(acc, { [x.key]: { action: () => action(x.value) } }),
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
        noInspector,
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
    const { isNotFound, isRecentAndInvalid, isLikelyPastTTL } = useValues(sessionRecordingDataLogic(logicProps))
    const { loadSnapshots } = useActions(sessionRecordingDataLogic(logicProps))
    const { isFullScreen, explorerMode, isBuffering, isCommenting } = useValues(sessionRecordingPlayerLogic(logicProps))
    const { setPlayNextAnimationInterrupted, setIsCommenting } = useActions(sessionRecordingPlayerLogic(logicProps))
    const speedHotkeys = useMemo(() => createPlaybackSpeedKey(setSpeed), [setSpeed])
    const { isVerticallyStacked, sidebarOpen } = useValues(playerSettingsLogic)

    useEffect(
        () => {
            if (isLikelyPastTTL) {
                posthog.capture('session loaded past ttl', {
                    viewedSessionRecording: sessionRecordingId,
                    recordingStartTime: sessionRecordingData?.start,
                })
            }
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [isLikelyPastTTL]
    )

    useEffect(
        () => {
            if (isRecentAndInvalid) {
                posthog.capture('session loaded recent and invalid', {
                    viewedSessionRecording: sessionRecordingId,
                    recordingStartTime: sessionRecordingData?.start,
                })
            }
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [isRecentAndInvalid]
    )

    useKeyboardHotkeys(
        {
            f: {
                action: () => setIsFullScreen(!isFullScreen),
            },
            c: {
                action: () => setIsCommenting(!isCommenting),
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

    usePageVisibilityCb((pageIsVisible) => {
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
                onMouseMove={() => setPlayNextAnimationInterrupted(true)}
                onMouseOut={() => setPlayNextAnimationInterrupted(false)}
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
                                {isRecentAndInvalid ? (
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
                                ) : isLikelyPastTTL ? (
                                    <div
                                        className="flex flex-1 flex-col items-center justify-center"
                                        data-attr="session-recording-player-past-ttl"
                                    >
                                        <SleepingHog height={200} />
                                        <h1>This recording is no longer available</h1>
                                        <p>
                                            We store session recordings for a limited time, and this one has expired and
                                            been deleted.
                                        </p>
                                        <div className="text-right">
                                            <LemonButton
                                                type="secondary"
                                                to="https://posthog.com/docs/session-replay/data-retention"
                                            >
                                                Learn more about data retention
                                            </LemonButton>
                                        </div>
                                    </div>
                                ) : (
                                    <div className="flex w-full h-full">
                                        <div className="flex flex-col flex-1 w-full">
                                            {!noMeta || isFullScreen ? <PlayerMeta /> : null}

                                            <div
                                                className="SessionRecordingPlayer__body"
                                                draggable={draggable}
                                                {...elementProps}
                                            >
                                                <PlayerFrame />
                                                <PlayerFrameOverlay />
                                                <PlayerFrameCommentOverlay />
                                            </div>
                                            <PlayerController />
                                        </div>
                                    </div>
                                )}
                            </div>

                            {!noInspector && <PlayerSidebar />}
                        </>
                    )}
                </FloatingContainerContext.Provider>
            </div>
            <SessionRecordingNextConfirmation />
        </BindLogic>
    )
}
