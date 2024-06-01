import './SessionRecordingPlayer.scss'

import { LemonSegmentedButton, LemonSegmentedButtonOption, LemonTag } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import { HotkeysInterface, useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { useMemo, useRef, useState } from 'react'
import { useNotebookDrag } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { PlayerController } from 'scenes/session-recordings/player/controller/PlayerController'
import { PlayerInspector } from 'scenes/session-recordings/player/inspector/PlayerInspector'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { RecordingNotFound } from 'scenes/session-recordings/player/RecordingNotFound'
import { MatchingEventsMatchType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'

import { NetworkView } from '../apm/NetworkView'
import { PlayerFrameOverlay } from './PlayerFrameOverlay'
import { PlayerMeta } from './PlayerMeta'
import { PlayerPersonMeta } from './PlayerPersonMeta'
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

type PlaybackViewType = 'waterfall' | 'playback' | 'inspector'

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
    const { isNotFound } = useValues(sessionRecordingDataLogic(logicProps))
    const { isFullScreen, explorerMode, isBuffering } = useValues(sessionRecordingPlayerLogic(logicProps))
    const speedHotkeys = useMemo(() => createPlaybackSpeedKey(setSpeed), [setSpeed])

    const allowWaterfallView = useFeatureFlag('SESSION_REPLAY_NETWORK_VIEW')

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

    const isWidescreen = !isFullScreen && size === 'wide'

    const [preferredInspectorStacking, setPreferredInspectorStacking] = useState(InspectorStacking.Horizontal)
    const [playerView, setPlayerView] = useState<PlaybackViewType>(isWidescreen ? 'inspector' : 'playback')

    const compactLayout = size === 'small'
    const layoutStacking = compactLayout ? InspectorStacking.Vertical : preferredInspectorStacking
    const isVerticallyStacked = layoutStacking === InspectorStacking.Vertical

    const { draggable, elementProps } = useNotebookDrag({ href: urls.replaySingle(sessionRecordingId) })

    if (isNotFound) {
        return (
            <div className="text-center">
                <RecordingNotFound />
            </div>
        )
    }

    const viewOptions: LemonSegmentedButtonOption<PlaybackViewType>[] = [{ value: 'playback', label: 'Playback' }]
    if (!noInspector) {
        viewOptions.push({ value: 'inspector', label: 'Inspector' })
    }
    if (allowWaterfallView) {
        viewOptions.push({
            value: 'waterfall',
            label: (
                <div className="space-x-1">
                    <span>Waterfall</span>
                    <LemonTag type="success">New</LemonTag>
                </div>
            ),
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
                                    data-attr="session-recording-player-view-choice"
                                    size="xsmall"
                                    value={playerView}
                                    onChange={setPlayerView}
                                    options={viewOptions}
                                />
                            </div>
                            {playerView === 'waterfall' ? (
                                <NetworkView sessionRecordingId={sessionRecordingId} />
                            ) : (
                                <div
                                    className={clsx('flex w-full h-full', {
                                        'SessionRecordingPlayer--stacked-vertically': isVerticallyStacked,
                                    })}
                                    ref={playerMainRef}
                                >
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

                                    {playerView === 'inspector' && (
                                        <PlayerInspector
                                            onClose={() => setPlayerView('playback')}
                                            isVerticallyStacked={isVerticallyStacked}
                                            toggleLayoutStacking={
                                                compactLayout
                                                    ? undefined
                                                    : () =>
                                                          setPreferredInspectorStacking(
                                                              preferredInspectorStacking === InspectorStacking.Vertical
                                                                  ? InspectorStacking.Horizontal
                                                                  : InspectorStacking.Vertical
                                                          )
                                            }
                                        />
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
