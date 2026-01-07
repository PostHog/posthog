import './SessionRecordingPlayer.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useMemo } from 'react'

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
import { urls } from 'scenes/urls'

import { PlayerFrame } from './PlayerFrame'
import { PlayerFrameMetaOverlay } from './PlayerFrameMetaOverlay'
import { PlayerFrameOverlay } from './PlayerFrameOverlay'
import { ClipOverlay } from './controller/ClipRecording'
import { PlayerController } from './controller/PlayerController'
import { PlayerMeta } from './player-meta/PlayerMeta'
import { PlayerMetaTopSettings } from './player-meta/PlayerMetaTopSettings'
import { playerSettingsLogic } from './playerSettingsLogic'
import { sessionRecordingDataCoordinatorLogic } from './sessionRecordingDataCoordinatorLogic'
import {
    ONE_FRAME_MS,
    PLAYBACK_SPEEDS,
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from './sessionRecordingPlayerLogic'
import { SessionRecordingPlayerExplorer } from './view-explorer/SessionRecordingPlayerExplorer'

export interface PurePlayerProps {
    noMeta?: boolean
    noBorder?: boolean
    playerRef: React.RefObject<HTMLDivElement>
}

export const createPlaybackSpeedKey = (action: (val: number) => void): HotkeysInterface => {
    return PLAYBACK_SPEEDS.map((x, i) => ({ key: `${i}`, value: x })).reduce(
        (acc, x) => Object.assign(acc, { [x.key]: { action: () => action(x.value) } }),
        {}
    )
}

export function PurePlayer({ noMeta = false, noBorder = false, playerRef }: PurePlayerProps): JSX.Element {
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
        setIsCommenting,
        takeScreenshot,
        setQuickEmojiIsOpen,
        setShowingClipParams,
        setPlayNextAnimationInterrupted,
    } = useActions(sessionRecordingPlayerLogic)

    const {
        logicProps,
        sessionRecordingId,
        sessionPlayerData,
        isFullScreen,
        explorerMode,
        isBuffering,
        isCommenting,
        quickEmojiIsOpen,
        showingClipParams,
        isMuted,
    } = useValues(sessionRecordingPlayerLogic)

    const { isNotFound, isRecentAndInvalid } = useValues(sessionRecordingDataCoordinatorLogic(logicProps))
    const { loadSnapshots } = useActions(sessionRecordingDataCoordinatorLogic(logicProps))

    const { isCinemaMode, showMetadataFooter } = useValues(playerSettingsLogic)
    const { setIsCinemaMode } = useActions(playerSettingsLogic)

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard
    const hidePlayerElements =
        mode === SessionRecordingPlayerMode.Screenshot || mode === SessionRecordingPlayerMode.Video

    useEffect(() => {
        if (hidePlayerElements) {
            setSkipInactivitySetting(false)
        }
    }, [mode, setSkipInactivitySetting, hidePlayerElements])

    useEffect(
        () => {
            if (isRecentAndInvalid) {
                posthog.capture('session loaded recent and invalid', {
                    viewedSessionRecording: sessionRecordingId,
                    recordingStartTime: sessionPlayerData?.start,
                })
            }
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [isRecentAndInvalid]
    )

    const speedHotkeys = useMemo(() => createPlaybackSpeedKey(setSpeed), [setSpeed])

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
        const timeout = setTimeout(() => {
            // oxlint-disable-next-line exhaustive-deps
            allowPlayerChromeToHide()
        }, 1500)
        return () => clearTimeout(timeout)
    }, [sessionRecordingId])

    if (isNotFound) {
        return (
            <div className="flex-1 w-full flex justify-center">
                <RecordingNotFound />
            </div>
        )
    }

    return (
        <div
            ref={playerRef}
            className={clsx(
                'SessionRecordingPlayer',
                {
                    'SessionRecordingPlayer--fullscreen': isFullScreen,
                    'SessionRecordingPlayer--no-border': noBorder,
                    'SessionRecordingPlayer--buffering': isBuffering,
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
                    <div className="SessionRecordingPlayer__main flex flex-col h-full w-full">
                        {isRecentAndInvalid ? (
                            <div className="flex flex-1 flex-col items-center justify-center">
                                <BuilderHog2 height={200} />
                                <h1>We're still working on it</h1>
                                <p>
                                    This recording hasn't been fully ingested yet. It should be ready to watch in a few
                                    minutes.
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
                                    {showMetadataFooter ? <PlayerFrameMetaOverlay /> : null}
                                    {!hidePlayerElements ? <PlayerController /> : null}
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </FloatingContainerContext.Provider>
        </div>
    )
}
