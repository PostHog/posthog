import './SessionRecordingPlayer.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useMemo, useRef } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { BuilderHog2 } from 'lib/components/hedgehogs'
import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import useIsHovering from 'lib/hooks/useIsHovering'
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
import { ClipOverlay } from './controller/ClipRecording'
import { PlayerController } from './controller/PlayerController'
import { PlayerMeta } from './player-meta/PlayerMeta'
import { PlayerMetaTopSettings } from './player-meta/PlayerMetaTopSettings'
import { playerSettingsLogic } from './playerSettingsLogic'
import { sessionRecordingDataCoordinatorLogic } from './sessionRecordingDataCoordinatorLogic'
import {
    ONE_FRAME_MS,
    PLAYBACK_SPEEDS,
    SessionRecordingPlayerLogicProps,
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from './sessionRecordingPlayerLogic'
import { SessionRecordingPlayerExplorer } from './view-explorer/SessionRecordingPlayerExplorer'

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
        setIsHovering,
        allowPlayerChromeToHide,
        setMuted,
    } = useActions(sessionRecordingPlayerLogic(logicProps))
    const { isNotFound, isRecentAndInvalid } = useValues(sessionRecordingDataCoordinatorLogic(logicProps))
    const { loadSnapshots } = useActions(sessionRecordingDataCoordinatorLogic(logicProps))
    const {
        isFullScreen,
        explorerMode,
        isBuffering,
        isCommenting,
        quickEmojiIsOpen,
        showingClipParams,
        resolution,
        isMuted,
    } = useValues(sessionRecordingPlayerLogic(logicProps))
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

    /**
     * If it's screenshot or video mode, we want to disable inactivity skipping.
     * For video, we also want to speed up the playback.
     */
    useEffect(() => {
        if (hidePlayerElements) {
            setSkipInactivitySetting(false)
        }
    }, [mode, setSkipInactivitySetting, hidePlayerElements, resolution])

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
            m: {
                action: () => setMuted(!isMuted),
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
    const showMeta = !(hidePlayerElements || (noMeta && !isFullScreen))

    const isHovering = useIsHovering(playerRef)

    useEffect(() => {
        // oxlint-disable-next-line exhaustive-deps
        setIsHovering(isHovering)
    }, [isHovering])

    useEffect(() => {
        // just once per recording clear the flag that forces the player chrome to show
        const timeout = setTimeout(() => {
            // oxlint-disable-next-line exhaustive-deps
            allowPlayerChromeToHide()
        }, 1500)
        return () => clearTimeout(timeout)
    }, [sessionRecordingId])

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
                                ) : (
                                    <div className="flex w-full h-full">
                                        <div className="flex flex-col flex-1 w-full relative">
                                            <div className="relative">
                                                {showMeta ? (
                                                    <>
                                                        <PlayerMeta />
                                                        <PlayerMetaTopSettings />
                                                    </>
                                                ) : null}
                                            </div>
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
        </BindLogic>
    )
}
