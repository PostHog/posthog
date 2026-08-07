import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useRef } from 'react'

import * as directorPng from '@posthog/brand/hoggies/png/director'

import { pngHoggie } from 'lib/brand/hoggies'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { cn } from 'lib/utils/css-classes'
import { Playlist } from 'scenes/session-recordings/playlist/Playlist'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { RecordingsUniversalFiltersEmbed } from '../filters/RecordingsUniversalFiltersEmbed'
import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { playlistFiltersLogic } from './playlistFiltersLogic'
import { SessionRecordingPlaylistLogicProps, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { SessionRecordingsPlaylistTroubleshooting } from './SessionRecordingsPlaylistTroubleshooting'

const HedgehogDirector = pngHoggie(directorPng)

export function SessionRecordingsPlaylist({
    ...props
}: SessionRecordingPlaylistLogicProps & {
    showContent?: boolean
    isSynthetic?: boolean
    description?: string
}): JSX.Element {
    const logicProps: SessionRecordingPlaylistLogicProps = {
        ...props,
        autoPlay: props.autoPlay ?? true,
        onlyPinned: props.type === 'collection',
    }

    const { sidePanelWidth } = useValues(panelLayoutLogic)
    const { isWindowLessThan } = useWindowSize({ widthOffset: sidePanelWidth })
    const windowSaysVertical = isWindowLessThan('xl')

    // Don't switch layout while in fullscreen — it would unmount the fullscreen element
    const layoutRef = useRef(windowSaysVertical)
    if (!document.fullscreenElement) {
        layoutRef.current = windowSaysVertical
    }
    const isVerticalLayout = layoutRef.current

    return (
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            <div className={cn('w-full h-full flex', isVerticalLayout ? 'flex-col' : 'flex-row gap-2')}>
                {isVerticalLayout ? <VerticalLayout {...props} /> : <HorizontalLayout {...props} />}
            </div>
        </BindLogic>
    )
}

function HorizontalLayout({
    ...props
}: SessionRecordingPlaylistLogicProps & {
    showContent?: boolean
    isSynthetic?: boolean
    description?: string
}): JSX.Element {
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
                              width: desiredSize ?? 320,
                              minWidth: 'min-content',
                              maxWidth: '50%',
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

function VerticalLayout({
    ...props
}: SessionRecordingPlaylistLogicProps & {
    showContent?: boolean
    isSynthetic?: boolean
    description?: string
}): JSX.Element {
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
        activeSessionRecordingId,
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
            {/* Keyed off the id rather than the list entry: a recording opened by direct link may never
                appear in the list, and a list reload must not unmount the player and throw away the
                "recording not found" explanation it is showing. */}
            {showContent && activeSessionRecordingId ? (
                <div className={cn('h-full', isFiltersExpanded && 'hidden')}>
                    <SessionRecordingPlayer
                        playerKey={props.logicKey ?? 'playlist'}
                        sessionRecordingId={activeSessionRecordingId}
                        matchingEventsMatchType={matchingEventsMatchType}
                        autoPlay={props.autoPlay}
                        onRecordingDeleted={() => {
                            loadAllRecordings()
                            setSelectedRecordingId(null)
                        }}
                        pinned={!!pinnedRecordings.find((x) => x.id === activeSessionRecordingId)}
                        setPinned={
                            props.onPinnedChange && activeSessionRecording
                                ? (pinned) => props.onPinnedChange?.(activeSessionRecording, pinned)
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
                <PlayerEmptyState type={props.type} />
            )}
            {resizer}
        </div>
    )
}

// The player pane has nothing to show. Say why, based on the list's actual state, and offer the
// matching next action: the list may be empty, collapsed out of view, or just have nothing selected.
function PlayerEmptyState({ type }: { type?: 'filters' | 'collection' }): JSX.Element {
    const { isPlaylistCollapsed } = useValues(playerSettingsLogic)
    const { setPlaylistCollapsed } = useActions(playerSettingsLogic)
    const { visiblePinnedRecordings, otherRecordings, sessionRecordingsAPIErrored, unusableEventsInFilter } =
        useValues(sessionRecordingsPlaylistLogic)

    if (isPlaylistCollapsed) {
        return (
            <div className="mt-20">
                <EmptyMessage
                    title="No recording selected"
                    description="The list is collapsed. Expand it to pick a recording to watch."
                    buttonText="Expand the list"
                    buttonOnClick={() => setPlaylistCollapsed(false)}
                    buttonDataAttr="player-empty-state-expand-playlist"
                />
            </div>
        )
    }

    // The troubleshooting guidance is about matching filtered recordings, so it only fits the
    // filters view; collections have their own empty-state copy on the list side.
    const listIsEmpty =
        type !== 'collection' &&
        !sessionRecordingsAPIErrored &&
        unusableEventsInFilter.length === 0 &&
        visiblePinnedRecordings.length === 0 &&
        otherRecordings.length === 0

    if (listIsEmpty) {
        return (
            <div className="mt-20 flex justify-center px-4">
                <div className="w-full max-w-100 text-sm text-secondary">
                    <SessionRecordingsPlaylistTroubleshooting />
                </div>
            </div>
        )
    }

    return (
        <div className="mt-20">
            <EmptyMessage
                title="No recording selected"
                description="Select a recording to watch."
                buttonText="Learn more about recordings"
                buttonTo="https://posthog.com/docs/user-guides/recordings"
            />
        </div>
    )
}
