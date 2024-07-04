import './SessionRecordingPlayer.scss'

import { LemonButton, LemonSegmentedButton, LemonSegmentedButtonOption, LemonTag } from '@posthog/lemon-ui'
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
import { PlayerInspector } from './inspector/PlayerInspector'
import { PlayerFrame } from './PlayerFrame'
import { PlayerFrameOverlay } from './PlayerFrameOverlay'
import { PlayerMeta } from './PlayerMeta'
import { PlayerPersonMeta } from './PlayerPersonMeta'
import { PlaybackViewMode, playerSettingsLogic } from './playerSettingsLogic'
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

enum InspectorStacking {
    Vertical = 'vertical',
    Horizontal = 'horizontal',
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
    const { preferredInspectorStacking, playbackViewMode } = useValues(playerSettingsLogic)
    const { setPreferredInspectorStacking, setPlaybackViewMode } = useActions(playerSettingsLogic)

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

    const compactLayout = size === 'small'
    const layoutStacking = compactLayout ? InspectorStacking.Vertical : preferredInspectorStacking
    const isVerticallyStacked = layoutStacking === InspectorStacking.Vertical

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

    const viewOptions: LemonSegmentedButtonOption<PlaybackViewMode>[] = [
        {
            value: PlaybackViewMode.Playback,
            label: 'Playback',
            'data-attr': 'session-recording-player-view-choice-playback',
        },
    ]
    if (!noInspector) {
        viewOptions.push({
            value: PlaybackViewMode.Inspector,
            label: 'Inspector',
            'data-attr': 'session-recording-player-view-choice-inspector',
        })

        viewOptions.push({
            value: PlaybackViewMode.Waterfall,
            label: (
                <div className="space-x-1">
                    <span>Waterfall</span>
                    <LemonTag type="success">New</LemonTag>
                </div>
            ),
            'data-attr': 'session-recording-player-view-choice-waterfall',
        })
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
                    },
                    `SessionRecordingPlayer--${size}`
                )}
                onClick={incrementClickCount}
            >
                <FloatingContainerContext.Provider value={playerRef}>
                    {explorerMode ? (
                        <SessionRecordingPlayerExplorer {...explorerMode} onClose={() => closeExplorer()} />
                    ) : (
                        <div className="flex flex-col h-full w-full">
                            <div className="flex justify-between items-center p-2 border-b">
                                <PlayerPersonMeta />

                                <LemonSegmentedButton
                                    size="xsmall"
                                    value={playbackViewMode}
                                    onChange={setPlaybackViewMode}
                                    options={viewOptions}
                                />
                            </div>
                            {playbackViewMode === PlaybackViewMode.Waterfall ? (
                                <NetworkView sessionRecordingId={sessionRecordingId} />
                            ) : (
                                <div
                                    className={clsx('flex w-full h-full', {
                                        'SessionRecordingPlayer--stacked-vertically': isVerticallyStacked,
                                    })}
                                    ref={playerMainRef}
                                >
                                    {cannotPlayback ? (
                                        <div className="flex flex-1 flex-col items-center justify-center">
                                            <BuilderHog2 height={200} />
                                            <h1>We're still working on it</h1>
                                            <p>
                                                This recording hasn't been fully ingested yet. It should be ready to
                                                watch in a few minutes.
                                            </p>
                                            <LemonButton type="secondary" onClick={loadSnapshots}>
                                                Reload
                                            </LemonButton>
                                        </div>
                                    ) : (
                                        <>
                                            <div className="SessionRecordingPlayer__main">
                                                {!noMeta || isFullScreen ? <PlayerMeta /> : null}

                                                <div
                                                    className="SessionRecordingPlayer__body"
                                                    draggable={draggable}
                                                    {...elementProps}
                                                >
                                                    <PlayerFrame />
                                                    <PlayerFrameOverlay />
                                                </div>
                                                <PlayerController linkIconsOnly={playerMainSize === 'small'} />
                                            </div>

                                            {playbackViewMode === PlaybackViewMode.Inspector && (
                                                <PlayerInspector
                                                    onClose={() => setPlaybackViewMode(PlaybackViewMode.Playback)}
                                                    isVerticallyStacked={isVerticallyStacked}
                                                    toggleLayoutStacking={
                                                        compactLayout
                                                            ? undefined
                                                            : () =>
                                                                  setPreferredInspectorStacking(
                                                                      preferredInspectorStacking ===
                                                                          InspectorStacking.Vertical
                                                                          ? InspectorStacking.Horizontal
                                                                          : InspectorStacking.Vertical
                                                                  )
                                                    }
                                                />
                                            )}
                                        </>
                                    )}
                                </div>
                            )}
                        </div>
                    )}
                </FloatingContainerContext.Provider>
            </div>
        </BindLogic>
    )
}
