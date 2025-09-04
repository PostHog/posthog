import './SessionRecordingPlayer.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useMemo, useRef } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { BuilderHog2, SleepingHog } from 'lib/components/hedgehogs'
import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import { HotkeysInterface, useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { usePageVisibilityCb } from 'lib/hooks/usePageVisibility'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { useNotebookDrag } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { RecordingNotFound } from 'scenes/session-recordings/player/RecordingNotFound'
import { PlayerFrameCommentOverlay } from 'scenes/session-recordings/player/commenting/PlayerFrameCommentOverlay'
import { MatchingEventsMatchType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'

import { PlayerFrame } from './PlayerFrame'
import { PlayerFrameOverlay } from './PlayerFrameOverlay'
import { PlayerSidebar } from './PlayerSidebar'
import { SessionRecordingNextConfirmation } from './SessionRecordingNextConfirmation'
import { ClipOverlay } from './controller/ClipRecording'
import { PlayerController } from './controller/PlayerController'
import { PlayerMeta } from './player-meta/PlayerMeta'
import { playerSettingsLogic } from './playerSettingsLogic'
import { sessionRecordingDataLogic } from './sessionRecordingDataLogic'
import {
    ONE_FRAME_MS,
    PLAYBACK_SPEEDS,
    SessionRecordingPlayerLogicProps,
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from './sessionRecordingPlayerLogic'
import { SessionRecordingPlayerExplorer } from './view-explorer/SessionRecordingPlayerExplorer'

const MAX_PLAYBACK_SPEED = 4

export interface SessionRecordingPlayerProps extends SessionRecordingPlayerLogicProps {
    noMeta?: boolean
    noBorder?: boolean
    noInspector?: boolean
    matchingEventsMatchType?: MatchingEventsMatchType
    accessToken?: string
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
        accessToken,
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
        accessToken,
    }
    const {
        incrementClickCount,
        setIsFullScreen,
        setPause,
        togglePlayPause,
        seekBackward,
        seekForward,
        setSpeed,
        setSkipInactivitySetting,
        closeExplorer,
    } = useActions(sessionRecordingPlayerLogic(logicProps))
    const { isNotFound, isRecentAndInvalid, isLikelyPastTTL } = useValues(sessionRecordingDataLogic(logicProps))
    const { loadSnapshots } = useActions(sessionRecordingDataLogic(logicProps))
    const { isFullScreen, explorerMode, isBuffering, isCommenting, quickEmojiIsOpen, showingClipParams } = useValues(
        sessionRecordingPlayerLogic(logicProps)
    )
    const {
        setPlayNextAnimationInterrupted,
        setIsCommenting,
        takeScreenshot,
        setQuickEmojiIsOpen,
        setShowingClipParams,
    } = useActions(sessionRecordingPlayerLogic(logicProps))
    const speedHotkeys = useMemo(() => createPlaybackSpeedKey(setSpeed), [setSpeed])
    const { isVerticallyStacked, sidebarOpen, isCinemaMode } = useValues(playerSettingsLogic)
    const { setIsCinemaMode } = useActions(playerSettingsLogic)

    // For export modes, we don't want to show the player elements
    const hidePlayerElements =
        mode === SessionRecordingPlayerMode.Screenshot || mode === SessionRecordingPlayerMode.Video

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

    /**
     * If it's screenshot or video mode, we want to disable inactivity skipping.
     * For video, we also want to speed up the playback.
     */
    useEffect(() => {
        if (hidePlayerElements) {
            setSkipInactivitySetting(false)
        }

        if (mode === SessionRecordingPlayerMode.Video) {
            // Not the maximum, but 4 for a balance between speed and quality
            setSpeed(MAX_PLAYBACK_SPEED)
        }
    }, [mode, setSkipInactivitySetting, setSpeed, hidePlayerElements])

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
            e: {
                action: () => setQuickEmojiIsOpen(!quickEmojiIsOpen),
            },
            s: {
                action: () => takeScreenshot(),
            },
            x: {
                action: () => setShowingClipParams(!showingClipParams),
            },
            t: {
                action: () => setIsCinemaMode(!isCinemaMode),
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
                                            {hidePlayerElements || (noMeta && !isFullScreen) ? null : <PlayerMeta />}
                                            <div
                                                className="SessionRecordingPlayer__body"
                                                draggable={draggable}
                                                {...elementProps}
                                            >
                                                <PlayerFrame />
                                                {!hidePlayerElements ? (
                                                    <>
                                                        <PlayerFrameOverlay />
                                                        <PlayerFrameCommentOverlay />
                                                        <ClipOverlay />
                                                    </>
                                                ) : null}
                                            </div>
                                            {!hidePlayerElements ? <PlayerController /> : null}
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
