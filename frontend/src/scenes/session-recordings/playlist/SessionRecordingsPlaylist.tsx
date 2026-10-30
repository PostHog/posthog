import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import * as directorPng from '@posthog/brand/hoggies/png/director'

import { pngHoggie } from 'lib/brand/hoggies'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic, reportFeatureFlagExposure } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { Playlist } from 'scenes/session-recordings/playlist/Playlist'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { HighlightPicksListColumn } from 'products/replay_vision/frontend/replay_scanners/components/HighlightPicksListColumn'
import { highlightPicksLogic } from 'products/replay_vision/frontend/replay_scanners/highlightPicksLogic'

import { RecordingsUniversalFiltersEmbed } from '../filters/RecordingsUniversalFiltersEmbed'
import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { playlistFiltersLogic } from './playlistFiltersLogic'
import { ReplayFilterBar } from './ReplayFilterBar'
import { isFeedReplayLayout, isNewReplayLayout } from './replayLayout'
import { ReplayListColumn } from './ReplayListColumn'
import { replayListColumnLogic } from './replayListColumnLogic'
import { ReplayListColumnWithPicks } from './ReplayListColumnWithPicks'
import { SessionRecordingPlaylistLogicProps, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

const HedgehogDirector = pngHoggie(directorPng)

type SessionRecordingsPlaylistProps = SessionRecordingPlaylistLogicProps & {
    showContent?: boolean
    isSynthetic?: boolean
    description?: string
    /** Replaces the shared replay troubleshooting panel when the list comes back empty. */
    listEmptyState?: JSX.Element
    picksInList?: boolean
    watchLayout?: boolean
}

export function SessionRecordingsPlaylist({
    picksInList = false,
    watchLayout = false,
    ...props
}: SessionRecordingsPlaylistProps): JSX.Element {
    const logicProps: SessionRecordingPlaylistLogicProps = {
        ...props,
        autoPlay: props.autoPlay ?? true,
        onlyPinned: props.type === 'collection',
    }
    const { featureFlags, receivedFeatureFlags } = useValues(featureFlagLogic)
    const { canOverrideLayout, staffLayoutOverride } = useValues(playerSettingsLogic)
    const layoutOverridden = canOverrideLayout && !!staffLayoutOverride
    useEffect(() => {
        // Opening the Replay page is the exposure. An override is not the flag's arm.
        if (watchLayout && receivedFeatureFlags && !layoutOverridden) {
            reportFeatureFlagExposure(featureFlags, FEATURE_FLAGS.REPLAY_WATCH_LAYOUT)
        }
    }, [watchLayout, receivedFeatureFlags, featureFlags, layoutOverridden])

    const { sidePanelWidth } = useValues(panelLayoutLogic)
    const { isWindowLessThan } = useWindowSize({ widthOffset: sidePanelWidth })
    const windowSaysVertical = isWindowLessThan('xl')

    // Don't switch layout while in fullscreen — it would unmount the fullscreen element
    const layoutRef = useRef(windowSaysVertical)
    if (!document.fullscreenElement) {
        layoutRef.current = windowSaysVertical
    }
    const isVerticalLayout = layoutRef.current

    const { replayLayout } = useValues(playerSettingsLogic)
    const feedLayout = watchLayout && isFeedReplayLayout(replayLayout)

    const columns = isVerticalLayout ? (
        <VerticalLayout {...props} picksInList={picksInList} watchLayout={watchLayout} />
    ) : feedLayout ? (
        <FeedHorizontalLayout {...props} picksInList={picksInList} watchLayout={watchLayout} />
    ) : (
        <HorizontalLayout {...props} picksInList={picksInList} watchLayout={watchLayout} />
    )
    const columnsClassName = cn('w-full flex', isVerticalLayout ? 'flex-col' : 'flex-row gap-2')

    const layout =
        feedLayout && props.type !== 'collection' ? (
            <div className="w-full h-full flex flex-col gap-2">
                <FeedFilterBar />
                <div className={cn(columnsClassName, 'flex-1 min-h-0')}>{columns}</div>
            </div>
        ) : (
            <div className={cn(columnsClassName, 'h-full')}>{columns}</div>
        )

    return (
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            {picksInList ? (
                <BindLogic
                    logic={highlightPicksLogic}
                    props={{ logicKey: logicProps.logicKey ?? 'playlist', playlistLogicProps: logicProps }}
                >
                    {layout}
                </BindLogic>
            ) : (
                layout
            )}
        </BindLogic>
    )
}

type LayoutProps = Omit<SessionRecordingsPlaylistProps, 'picksInList' | 'watchLayout'> & {
    picksInList: boolean
    watchLayout: boolean
}

function PlaylistColumn({ picksInList, ...props }: LayoutProps): JSX.Element {
    const { isPlaylistCollapsed, replayLayout } = useValues(playerSettingsLogic)
    if (props.watchLayout && isNewReplayLayout(replayLayout)) {
        return <WatchPlaylistColumn {...props} picksInList={picksInList} />
    }
    if (isPlaylistCollapsed || !picksInList) {
        return <Playlist {...props} />
    }
    return <HighlightPicksListColumn recordingsList={<Playlist {...props} />} />
}

// Owns the column logic, so the chosen segment survives the column unmounting when the list collapses, and only
// the new layout mounts it.
function WatchPlaylistColumn({ picksInList, ...props }: LayoutProps): JSX.Element {
    const { isPlaylistCollapsed } = useValues(playerSettingsLogic)
    const playlistLogic = useMountedLogic(sessionRecordingsPlaylistLogic)
    const logicKey = props.logicKey ?? 'playlist'
    useMountedLogic(replayListColumnLogic({ logicKey, playlistLogicProps: playlistLogic.props }))
    if (isPlaylistCollapsed) {
        return <Playlist {...props} />
    }
    const collections = !props.type
    return picksInList ? (
        <ReplayListColumnWithPicks
            logicKey={logicKey}
            recordingsList={<Playlist {...props} />}
            collections={collections}
        />
    ) : (
        <ReplayListColumn
            logicKey={logicKey}
            recordingsList={<Playlist {...props} />}
            picksMode={null}
            collections={collections}
        />
    )
}

function HorizontalLayout({ picksInList, ...props }: LayoutProps): JSX.Element {
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
                <PlaylistColumn {...props} picksInList={picksInList} />
                {!isPlaylistCollapsed && (
                    <Resizer {...resizerLogicProps} visible={false} offset="0.25rem" handleClassName="rounded my-1" />
                )}
            </div>
            <PlayerWrapper {...props} className="h-full flex-1 shrink" />
        </>
    )
}

function FeedHorizontalLayout({ picksInList, ...props }: LayoutProps): JSX.Element {
    const feedRef = useRef<HTMLDivElement>(null)

    const { isPlaylistCollapsed } = useValues(playerSettingsLogic)
    const { setPlaylistCollapsed } = useActions(playerSettingsLogic)
    const resizerLogicProps: ResizerLogicProps = {
        logicKey: 'playlist-resizer-feed',
        containerRef: feedRef,
        persistent: true,
        persistPrefix: '2026-10-23',
        placement: 'left',
        closeThreshold: 100,
        onToggleClosed: (shouldBeClosed) => setPlaylistCollapsed(shouldBeClosed),
    }

    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    return (
        <>
            <PlayerWrapper {...props} className="h-full flex-1 shrink" />
            <div
                ref={feedRef}
                className={cn('relative flex flex-col shrink-0', {
                    'w-3': isPlaylistCollapsed,
                })}
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    isPlaylistCollapsed
                        ? {}
                        : {
                              width: desiredSize ?? 400,
                              minWidth: 'min-content',
                              maxWidth: '50%',
                          }
                }
                data-attr="replay-feed-column"
            >
                <PlaylistColumn {...props} picksInList={picksInList} />
                {!isPlaylistCollapsed && (
                    <Resizer {...resizerLogicProps} visible={false} offset="0.25rem" handleClassName="rounded my-1" />
                )}
            </div>
        </>
    )
}

function FeedFilterBar(): JSX.Element {
    const { filters, totalFiltersCount, activeSessionRecordingId } = useValues(sessionRecordingsPlaylistLogic)
    const { setFilters, maybeLoadSessionRecordings } = useActions(sessionRecordingsPlaylistLogic)

    return (
        <ReplayFilterBar
            filters={filters}
            setFilters={setFilters}
            totalFiltersCount={totalFiltersCount}
            currentSessionRecordingId={activeSessionRecordingId}
            onReload={() => maybeLoadSessionRecordings()}
            savedFilterChips
        />
    )
}

function VerticalLayout({ picksInList, ...props }: LayoutProps): JSX.Element {
    const playerRef = useRef<HTMLDivElement>(null)

    const { isPlaylistCollapsed, replayLayout } = useValues(playerSettingsLogic)
    const { setPlaylistCollapsed } = useActions(playerSettingsLogic)
    const watchStack = props.watchLayout && isNewReplayLayout(replayLayout)

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
                style={
                    isPlaylistCollapsed
                        ? {}
                        : { height: desiredSize ?? (watchStack ? '50vh' : undefined), minHeight: 300 }
                }
                className={cn(
                    isPlaylistCollapsed ? 'flex-1' : 'pb-2 shrink-0',
                    watchStack && 'Playlist__main--stacked'
                )}
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
            <div
                className={cn('relative flex flex-col min-h-0', isPlaylistCollapsed ? 'h-5' : 'flex-1')}
                data-stacked={watchStack || undefined}
            >
                <PlaylistColumn {...props} picksInList={picksInList} />
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
    watchLayout?: boolean
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
    const { setFilters, applySavedFilter, resetFilters, setSelectedRecordingId, loadAllRecordings } =
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
                        applySavedFilter={applySavedFilter}
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
                        watchLayout={props.watchLayout}
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
                        description="Pick a recording from the list to watch it"
                        buttonText="Learn more about recordings"
                        buttonTo="https://posthog.com/docs/user-guides/recordings"
                    />
                </div>
            )}
            {resizer}
        </div>
    )
}
