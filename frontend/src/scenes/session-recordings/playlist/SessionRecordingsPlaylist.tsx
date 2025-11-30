import { BindLogic, useActions, useValues } from 'kea'
import { useRef } from 'react'

import { Link } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { cn } from 'lib/utils/css-classes'
import { Playlist } from 'scenes/session-recordings/playlist/Playlist'
import { urls } from 'scenes/urls'

import { ReplayTabs } from '~/types'

import { RecordingsUniversalFiltersEmbed } from '../filters/RecordingsUniversalFiltersEmbed'
import { PurePlayer } from '../player/PurePlayer'
import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { SessionRecordingPlayerLogicProps, sessionRecordingPlayerLogic } from '../player/sessionRecordingPlayerLogic'
import { PlayerSidebarContent } from '../player/sidebar/PlayerSidebarContent'
import { SessionRecordingsPlaylistTroubleshooting } from './SessionRecordingsPlaylistTroubleshooting'
import { playlistFiltersLogic } from './playlistFiltersLogic'
import { SessionRecordingPlaylistLogicProps, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export function SessionRecordingsPlaylist({
    showContent = true,
    /**
     * Historically we allowed playlists to mix filters and pinned recordings.
     * But we don't want to... however, some users might use playlists with pinned recordings
     * and filters.
     *
     * This prop allows us to allow that case or not.
     * Eventually this will be removed, and we'll only allow one or the other.
     */
    canMixFiltersAndPinned = true,
    type = 'filters',
    isSynthetic = false,
    description,
    ...props
}: SessionRecordingPlaylistLogicProps & {
    showContent?: boolean
    canMixFiltersAndPinned?: boolean
    type?: 'filters' | 'collection'
    isSynthetic?: boolean
    description?: string
}): JSX.Element {
    const logicProps: SessionRecordingPlaylistLogicProps = {
        ...props,
        autoPlay: props.autoPlay ?? true,
    }
    const thePlaylistLogic = sessionRecordingsPlaylistLogic(logicProps)
    const {
        filters,
        pinnedRecordings,
        matchingEventsMatchType,
        otherRecordings,
        activeSessionRecordingId,
        allowHogQLFilters,
        allowReplayGroupsFilters,
        totalFiltersCount,
    } = useValues(thePlaylistLogic)
    const { setSelectedRecordingId, setFilters, resetFilters, loadAllRecordings } = useActions(thePlaylistLogic)

    const { isFiltersExpanded } = useValues(playlistFiltersLogic)
    const { sidebarOpen, isVerticallyStacked } = useValues(playerSettingsLogic)
    const { setSidebarOpen } = useActions(playerSettingsLogic)

    const playlistPanelRef = useRef<HTMLDivElement>(null)
    const playerPanelRef = useRef<HTMLDivElement>(null)
    const activityPanelRef = useRef<HTMLDivElement>(null)

    const playlistResizerLogicProps: ResizerLogicProps = {
        logicKey: `playlist-list-resizer-${isVerticallyStacked ? 'vertical' : 'horizontal'}`,
        containerRef: isVerticallyStacked ? playerPanelRef : playlistPanelRef,
        persistent: true,
        closeThreshold: 100,
        placement: isVerticallyStacked ? 'bottom' : 'right',
    }

    const activityResizerLogicProps: ResizerLogicProps = {
        logicKey: `playlist-activity-resizer-${isVerticallyStacked ? 'vertical' : 'horizontal'}`,
        containerRef: activityPanelRef,
        persistent: true,
        closeThreshold: 100,
        placement: isVerticallyStacked ? 'top' : 'left',
        onToggleClosed: (shouldBeClosed) => setSidebarOpen(!shouldBeClosed),
    }

    const { desiredSize: playlistDesiredSize } = useValues(resizerLogic(playlistResizerLogicProps))
    const { desiredSize: activityDesiredSize } = useValues(resizerLogic(activityResizerLogicProps))

    const activeRecording = [...pinnedRecordings, ...otherRecordings].find((r) => r.id === activeSessionRecordingId)

    const playerLogicProps: SessionRecordingPlayerLogicProps = {
        sessionRecordingId: activeSessionRecordingId ?? '',
        playerKey: props.logicKey ?? 'playlist',
        matchingEventsMatchType,
        autoPlay: logicProps.autoPlay,
        onRecordingDeleted: () => {
            loadAllRecordings()
            setSelectedRecordingId(null)
        },
        pinned: !!pinnedRecordings.find((x) => x.id === activeSessionRecordingId),
        setPinned: props.onPinnedChange
            ? (pinned) => {
                  if (!activeSessionRecordingId || !activeRecording) {
                      return
                  }
                  props.onPinnedChange?.(activeRecording, pinned)
              }
            : undefined,
    }

    const hasActiveRecording = showContent && activeSessionRecordingId

    return (
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            <div className={cn('w-full flex', isVerticallyStacked ? 'flex-col-reverse' : 'flex-row h-full')}>
                {/* Playlist Panel */}
                <div
                    ref={isVerticallyStacked ? undefined : playlistPanelRef}
                    className={cn('flex flex-col shrink-0', isVerticallyStacked ? 'w-full' : 'h-full')}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={
                        isVerticallyStacked
                            ? { height: 300, maxHeight: 300 }
                            : { width: playlistDesiredSize ?? 320, minWidth: '16rem' }
                    }
                >
                    <Playlist
                        type={type}
                        shortId={props.logicKey}
                        canMixFiltersAndPinned={canMixFiltersAndPinned}
                        logicKey={logicProps.logicKey}
                        showFilters
                        listEmptyState={
                            type === 'collection' ? (
                                <CollectionEmptyState isSynthetic={isSynthetic} description={description} />
                            ) : (
                                <ListEmptyState />
                            )
                        }
                    />
                </div>

                {/* Resizer between Playlist and Player */}
                <div className={cn('relative shrink-0', isVerticallyStacked ? 'h-2 w-full' : 'w-2 h-full')}>
                    <Resizer
                        logicKey={playlistResizerLogicProps.logicKey}
                        placement={isVerticallyStacked ? 'bottom' : 'right'}
                        containerRef={isVerticallyStacked ? playerPanelRef : playlistPanelRef}
                        closeThreshold={100}
                        offset="50%"
                        className={cn('Playlist__resizer', isVerticallyStacked ? 'mx-1' : 'my-1')}
                    />
                </div>

                {/* Player and Activity Panel */}
                {isFiltersExpanded ? (
                    <div className="flex-1 min-w-0 min-h-0 h-full bg-surface-primary p-2 border border-primary rounded overflow-auto">
                        <RecordingsUniversalFiltersEmbed
                            resetFilters={resetFilters}
                            filters={filters}
                            setFilters={setFilters}
                            totalFiltersCount={totalFiltersCount}
                            allowReplayHogQLFilters={allowHogQLFilters}
                            allowReplayGroupsFilters={allowReplayGroupsFilters}
                        />
                    </div>
                ) : hasActiveRecording ? (
                    <BindLogic
                        logic={sessionRecordingPlayerLogic}
                        props={playerLogicProps}
                        key={activeSessionRecordingId}
                    >
                        <div
                            ref={playerPanelRef}
                            className={cn(
                                'min-w-0 flex',
                                isVerticallyStacked ? 'flex-col w-full shrink-0' : 'flex-row h-full flex-1'
                            )}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={
                                isVerticallyStacked
                                    ? { height: Math.max(playlistDesiredSize ?? 500, 400), minHeight: 400 }
                                    : undefined
                            }
                        >
                            <div
                                className={cn('flex-1 min-w-0', isVerticallyStacked ? 'w-full' : 'h-full')}
                                // eslint-disable-next-line react/forbid-dom-props
                                style={isVerticallyStacked ? { minHeight: 200 } : undefined}
                            >
                                <PurePlayer noBorder />
                            </div>

                            {sidebarOpen && (
                                <>
                                    <div
                                        className={cn(
                                            'relative shrink-0',
                                            isVerticallyStacked ? 'h-2 w-full' : 'w-2 h-full'
                                        )}
                                    >
                                        <Resizer
                                            logicKey={activityResizerLogicProps.logicKey}
                                            placement={isVerticallyStacked ? 'top' : 'left'}
                                            containerRef={activityPanelRef}
                                            closeThreshold={100}
                                            offset="50%"
                                            className={cn(
                                                'SessionRecordingPlayer__resizer',
                                                isVerticallyStacked ? 'mx-1' : 'my-1'
                                            )}
                                        />
                                    </div>

                                    <div
                                        ref={activityPanelRef}
                                        className={cn(
                                            'shrink-0 flex flex-col overflow-hidden bg-surface-primary border border-primary rounded',
                                            isVerticallyStacked ? 'w-full' : 'h-full'
                                        )}
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={
                                            isVerticallyStacked
                                                ? { height: activityDesiredSize ?? 300, minHeight: 210 }
                                                : { width: activityDesiredSize ?? 400, minWidth: 320 }
                                        }
                                    >
                                        <PlayerSidebarContent />
                                    </div>
                                </>
                            )}
                        </div>
                    </BindLogic>
                ) : (
                    <div className="flex-1 min-w-0 min-h-0 h-full flex items-center justify-center border border-primary rounded bg-surface-primary">
                        <EmptyMessage
                            title="No recording selected"
                            description="Please select a recording from the list on the left"
                            buttonText="Learn more about recordings"
                            buttonTo="https://posthog.com/docs/user-guides/recordings"
                        />
                    </div>
                )}
            </div>
        </BindLogic>
    )
}

const ListEmptyState = (): JSX.Element => {
    const { sessionRecordingsAPIErrored, unusableEventsInFilter } = useValues(sessionRecordingsPlaylistLogic)

    return (
        <div className="p-3 text-sm text-secondary">
            {sessionRecordingsAPIErrored ? (
                <LemonBanner type="error">Error while trying to load recordings.</LemonBanner>
            ) : unusableEventsInFilter.length ? (
                <UnusableEventsWarning unusableEventsInFilter={unusableEventsInFilter} />
            ) : (
                <SessionRecordingsPlaylistTroubleshooting />
            )}
        </div>
    )
}

const CollectionEmptyState = ({
    isSynthetic,
    description,
}: {
    isSynthetic?: boolean
    description?: string
}): JSX.Element => {
    const { sessionRecordingsAPIErrored, unusableEventsInFilter } = useValues(sessionRecordingsPlaylistLogic)

    return (
        <div className="p-3 text-sm text-secondary">
            {sessionRecordingsAPIErrored ? (
                <LemonBanner type="error">Error while trying to load recordings.</LemonBanner>
            ) : unusableEventsInFilter.length ? (
                <UnusableEventsWarning unusableEventsInFilter={unusableEventsInFilter} />
            ) : isSynthetic ? (
                <div className="flex flex-col gap-2">
                    <h3 className="title text-secondary mb-0">No recordings yet</h3>
                    <p>{description || 'This collection is automatically populated.'}</p>
                </div>
            ) : (
                <div className="flex flex-col gap-2">
                    <h3 className="title text-secondary mb-0">No recordings in this collection</h3>
                    <p>
                        To add recordings to this collection, go to the{' '}
                        <Link to={urls.replay(ReplayTabs.Home)}>Recordings</Link> tab, click on a recording, then click
                        "+ Add to collection" and select this collection from the list.
                    </p>
                </div>
            )}
        </div>
    )
}

const UnusableEventsWarning = (props: { unusableEventsInFilter: string[] }): JSX.Element => {
    return (
        <LemonBanner type="warning">
            <p>Cannot use these events to filter for session recordings:</p>
            <li className="my-1">
                {props.unusableEventsInFilter.map((event) => (
                    <span key={event}>"{event}"</span>
                ))}
            </li>
            <p>
                Events have to have a <PropertyKeyInfo value="$session_id" /> to be used to filter recordings. This is
                added automatically by{' '}
                <Link to="https://posthog.com/docs/libraries/js" target="_blank">
                    the Web SDK
                </Link>
                ,{' '}
                <Link to="https://posthog.com/docs/libraries" target="_blank">
                    and the Mobile SDKs (Android, iOS, React Native and Flutter)
                </Link>
            </p>
        </LemonBanner>
    )
}
