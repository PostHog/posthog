import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import * as directorPng from '@posthog/brand/hoggies/png/director'

import { pngHoggie } from 'lib/brand/hoggies'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { TAILWIND_BREAKPOINTS } from 'lib/constants'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { cn } from 'lib/utils/css-classes'
import { Playlist } from 'scenes/session-recordings/playlist/Playlist'

import { RecordingsUniversalFiltersEmbed } from '../filters/RecordingsUniversalFiltersEmbed'
import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { playlistFiltersLogic } from './playlistFiltersLogic'
import { SessionRecordingPlaylistLogicProps, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

const HedgehogDirector = pngHoggie(directorPng)

/** Narrower than this and the list stacks over the player instead of sitting beside it. */
const HORIZONTAL_LAYOUT_MIN_WIDTH = TAILWIND_BREAKPOINTS.xl
/** Stays below half of HORIZONTAL_LAYOUT_MIN_WIDTH so the list column's 50% cap always wins. */
const LIST_MIN_WIDTH = 240
const LIST_DEFAULT_WIDTH = 320

type SessionRecordingsPlaylistProps = SessionRecordingPlaylistLogicProps & {
    showContent?: boolean
    isSynthetic?: boolean
    description?: string
    /** Replaces the shared replay troubleshooting panel when the list comes back empty. */
    listEmptyState?: JSX.Element
}

export function SessionRecordingsPlaylist({ ...props }: SessionRecordingsPlaylistProps): JSX.Element {
    const logicProps: SessionRecordingPlaylistLogicProps = {
        ...props,
        autoPlay: props.autoPlay ?? true,
        onlyPinned: props.type === 'collection',
    }

    // The nav sidebar, a tab column, a notebook node and a side panel all take width the window knows
    // nothing about, so measure the container the playlist actually gets.
    const containerRef = useRef<HTMLDivElement>(null)
    const [containerWidth, setContainerWidth] = useState<number | null>(null)

    useLayoutEffect(() => {
        const container = containerRef.current
        if (!container) {
            return
        }
        // Read before the first paint so the layout mounts once — re-mounting restarts snapshot loading.
        setContainerWidth(container.clientWidth)
        const observer = new ResizeObserver(() => setContainerWidth(container.clientWidth))
        observer.observe(container)
        return () => observer.disconnect()
    }, [])

    // Fullscreen has to be state rather than a live `document.fullscreenElement` read. Leaving fullscreen
    // schedules no render of its own, so the guard below would hold a stale layout until something else
    // happened to re-render.
    const [isFullscreen, setIsFullscreen] = useState(() => !!document.fullscreenElement)

    useEffect(() => {
        const onFullscreenChange = (): void => setIsFullscreen(!!document.fullscreenElement)
        document.addEventListener('fullscreenchange', onFullscreenChange)
        return () => document.removeEventListener('fullscreenchange', onFullscreenChange)
    }, [])

    const containerSaysVertical = containerWidth !== null && containerWidth < HORIZONTAL_LAYOUT_MIN_WIDTH

    // Don't switch layout while in fullscreen — it would unmount the fullscreen element
    const layoutRef = useRef(containerSaysVertical)
    if (!isFullscreen) {
        layoutRef.current = containerSaysVertical
    }
    const isVerticalLayout = layoutRef.current

    return (
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            <div
                ref={containerRef}
                className={cn('w-full h-full flex', isVerticalLayout ? 'flex-col' : 'flex-row gap-2')}
            >
                {containerWidth === null ? null : isVerticalLayout ? (
                    <VerticalLayout {...props} />
                ) : (
                    <HorizontalLayout {...props} />
                )}
            </div>
        </BindLogic>
    )
}

function HorizontalLayout({ ...props }: SessionRecordingsPlaylistProps): JSX.Element {
    const playlistRef = useRef<HTMLDivElement>(null)

    const { isPlaylistCollapsed } = useValues(playerSettingsLogic)
    const { setPlaylistCollapsed } = useActions(playerSettingsLogic)
    const resizerLogicProps: ResizerLogicProps = {
        logicKey: 'playlist-resizer-horizontal',
        containerRef: playlistRef,
        persistent: true,
        persistPrefix: '2025-12-29',
        placement: 'right',
        closeThreshold: 100,
        onToggleClosed: (shouldBeClosed) => setPlaylistCollapsed(shouldBeClosed),
    }

    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    return (
        <>
            <div
                ref={playlistRef}
                className={cn('relative flex flex-col shrink-0', {
                    'w-3': isPlaylistCollapsed,
                })}
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    isPlaylistCollapsed
                        ? {}
                        : {
                              // min-width beats max-width in CSS, so a separate minWidth let the column
                              // outgrow its own cap. Nested, the cap holds.
                              width: `min(max(${desiredSize ?? LIST_DEFAULT_WIDTH}px, ${LIST_MIN_WIDTH}px), 50%)`,
                          }
                }
            >
                <Playlist {...props} />
                {!isPlaylistCollapsed && (
                    <Resizer {...resizerLogicProps} visible={false} offset="0.25rem" handleClassName="rounded my-1" />
                )}
            </div>
            <PlayerWrapper {...props} className="h-full flex-1 shrink" />
        </>
    )
}

function VerticalLayout({ ...props }: SessionRecordingsPlaylistProps): JSX.Element {
    const playerRef = useRef<HTMLDivElement>(null)

    const { isPlaylistCollapsed } = useValues(playerSettingsLogic)
    const { setPlaylistCollapsed } = useActions(playerSettingsLogic)

    const resizerLogicProps: ResizerLogicProps = {
        logicKey: 'playlist-resizer-vertical',
        containerRef: playerRef,
        persistent: true,
        persistPrefix: '2025-12-29',
        placement: 'bottom',
        closeThreshold: 100,
        onToggleClosed: (shouldBeClosed) => setPlaylistCollapsed(shouldBeClosed),
    }

    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    return (
        <>
            <PlayerWrapper
                {...props}
                containerRef={playerRef}
                style={isPlaylistCollapsed ? {} : { height: desiredSize ?? undefined, minHeight: 300 }}
                className={isPlaylistCollapsed ? 'flex-1' : 'pb-2 shrink-0'}
                resizer={
                    !isPlaylistCollapsed ? (
                        <Resizer
                            {...resizerLogicProps}
                            visible={false}
                            offset="0.25rem"
                            handleClassName="rounded mx-1"
                        />
                    ) : null
                }
            />
            <div className={cn('relative flex flex-col min-h-0', isPlaylistCollapsed ? 'h-5' : 'flex-1')}>
                <Playlist {...props} />
            </div>
        </>
    )
}

function PlayerWrapper({
    showContent = true,
    containerRef,
    style,
    resizer,
    className,
    ...props
}: SessionRecordingPlaylistLogicProps & {
    showContent?: boolean
    type?: 'filters' | 'collection'
    isSynthetic?: boolean
    description?: string
    containerRef?: React.RefObject<HTMLDivElement>
    style?: React.CSSProperties
    resizer?: React.ReactNode
    className?: string
}): JSX.Element {
    const {
        filters,
        visiblePinnedRecordings: pinnedRecordings,
        matchingEventsMatchType,
        exposureSkipExperimentId,
        activeSessionRecording,
        allowHogQLFilters,
        totalFiltersCount,
        nextSessionRecording,
        pinnedFilters,
        sessionRecordingsResponseLoading,
    } = useValues(sessionRecordingsPlaylistLogic)
    const { setFilters, resetFilters, setSelectedRecordingId, loadAllRecordings } =
        useActions(sessionRecordingsPlaylistLogic)

    const { isFiltersExpanded } = useValues(playlistFiltersLogic)

    const onPlayNextRecording = useCallback(() => {
        if (nextSessionRecording?.id && !isFiltersExpanded) {
            setSelectedRecordingId(nextSessionRecording.id)
        }
    }, [nextSessionRecording, setSelectedRecordingId, isFiltersExpanded])

    return (
        <div
            ref={containerRef}
            className={cn('Playlist__main relative overflow-hidden', className, 'min-h-96')}
            // eslint-disable-next-line react/forbid-dom-props
            style={style}
        >
            {isFiltersExpanded && (
                <div className="h-full overflow-y-auto rounded border">
                    <RecordingsUniversalFiltersEmbed
                        resetFilters={resetFilters}
                        filters={filters}
                        setFilters={setFilters}
                        totalFiltersCount={totalFiltersCount}
                        allowReplayHogQLFilters={allowHogQLFilters}
                        pinnedFilters={pinnedFilters}
                    />
                </div>
            )}
            {showContent && activeSessionRecording ? (
                <div className={cn('h-full', isFiltersExpanded && 'hidden')}>
                    <SessionRecordingPlayer
                        playerKey={props.logicKey ?? 'playlist'}
                        sessionRecordingId={activeSessionRecording.id}
                        matchingEventsMatchType={matchingEventsMatchType}
                        exposureSkipExperimentId={exposureSkipExperimentId}
                        autoPlay={props.autoPlay}
                        onRecordingDeleted={() => {
                            loadAllRecordings()
                            setSelectedRecordingId(null)
                        }}
                        pinned={!!pinnedRecordings.find((x) => x.id === activeSessionRecording.id)}
                        setPinned={
                            props.onPinnedChange
                                ? (pinned) => {
                                      if (!activeSessionRecording.id) {
                                          return
                                      }
                                      props.onPinnedChange?.(activeSessionRecording, pinned)
                                  }
                                : undefined
                        }
                        playNextRecording={nextSessionRecording?.id ? onPlayNextRecording : undefined}
                    />
                </div>
            ) : sessionRecordingsResponseLoading ? (
                <div className="relative flex flex-col h-full p-4">
                    {/* Player skeleton background */}
                    <div className="flex-1 flex flex-col gap-2">
                        {/* Video area skeleton */}
                        <LemonSkeleton className="flex-1 w-full rounded" />
                        {/* Controller bar skeleton */}
                        <div className="flex gap-2">
                            <LemonSkeleton className="h-10 w-20" />
                            <LemonSkeleton className="h-10 flex-1" />
                            <LemonSkeleton className="h-10 w-32" />
                        </div>
                    </div>

                    {/* Centered hedgehog overlay */}
                    <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                        <HedgehogDirector className="w-60 h-60" />
                        <div className="mt-4 flex items-center gap-2">
                            <Spinner textColored />
                            <span className="text-secondary">Loading recordings...</span>
                        </div>
                    </div>
                </div>
            ) : (
                <div className="mt-20">
                    <EmptyMessage
                        title="No recording selected"
                        description="Please select a recording from the list on the left"
                        buttonText="Learn more about recordings"
                        buttonTo="https://posthog.com/docs/user-guides/recordings"
                    />
                </div>
            )}
            {resizer}
        </div>
    )
}
