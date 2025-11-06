import { BindLogic, useActions, useValues } from 'kea'

import { LemonBadge, LemonButton, Link, Spinner } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { Playlist, PlaylistSection } from 'scenes/session-recordings/playlist/Playlist'
import { urls } from 'scenes/urls'

import { ReplayTabs } from '~/types'

import {
    RecordingsUniversalFiltersEmbed,
    RecordingsUniversalFiltersEmbedButton,
} from '../filters/RecordingsUniversalFiltersEmbed'
import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { SessionRecordingPreview } from './SessionRecordingPreview'
import { SessionRecordingsPlaylistTopSettings } from './SessionRecordingsPlaylistSettings'
import { SessionRecordingsPlaylistTroubleshooting } from './SessionRecordingsPlaylistTroubleshooting'
import { SessionRecordingPlaylistLogicProps, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export function SessionRecordingsPlaylist({
    showContent = true,
    canMixFiltersAndPinned = true,
    type = 'filters',
    isSynthetic = false,
    description,
    ...props
}: SessionRecordingPlaylistLogicProps & {
    showContent?: boolean
    /**
     * Historically we allowed playlists to mix filters and pinned recordings.
     * But we don't want to... however, some users might use playlists with pinned recordings
     * and filters.
     *
     * This prop allows us to allow that case or not.
     * Eventually this will be removed, and we'll only allow one or the other.
     */
    canMixFiltersAndPinned?: boolean
    type?: 'filters' | 'collection'
    isSynthetic?: boolean
    description?: string
}): JSX.Element {
    const logicProps: SessionRecordingPlaylistLogicProps = {
        ...props,
        autoPlay: props.autoPlay ?? true,
    }
    const playlistLogic = sessionRecordingsPlaylistLogic(logicProps)
    const {
        filters,
        pinnedRecordings,
        matchingEventsMatchType,
        sessionRecordingsResponseLoading,
        otherRecordings,
        activeSessionRecordingId,
        hasNext,
        allowHogQLFilters,
        allowReplayGroupsFilters,
        totalFiltersCount,
    } = useValues(playlistLogic)
    const { maybeLoadSessionRecordings, setSelectedRecordingId, setFilters, resetFilters } = useActions(playlistLogic)

    const notebookNode = useNotebookNode()
    const sections: PlaylistSection[] = []

    if (type === 'collection' || pinnedRecordings.length > 0) {
        sections.push({
            key: 'pinned',
            title: (
                <div className="flex flex-row deprecated-space-x-1 items-center">
                    <span>Pinned recordings</span>
                    <LemonBadge.Number count={pinnedRecordings.length} status="muted" size="small" />
                </div>
            ),
            items: pinnedRecordings,
            render: ({ item, isActive }) => <SessionRecordingPreview recording={item} isActive={isActive} selectable />,
            initiallyOpen: true,
        })
    } else {
        sections.push({
            key: 'other',
            title: (
                <div className="flex flex-row deprecated-space-x-1 items-center">
                    <span>Results</span>
                    <LemonBadge.Number count={otherRecordings.length} status="muted" size="small" />
                </div>
            ),
            items: otherRecordings,
            initiallyOpen: !pinnedRecordings.length,
            render: ({ item, isActive }) => <SessionRecordingPreview recording={item} isActive={isActive} selectable />,
            footer: (
                <div className="p-4">
                    <div className="h-10 flex items-center justify-center gap-2 text-secondary">
                        {sessionRecordingsResponseLoading ? (
                            <>
                                <Spinner textColored /> Loading older recordings
                            </>
                        ) : hasNext ? (
                            <LemonButton onClick={() => maybeLoadSessionRecordings('older')}>Load more</LemonButton>
                        ) : (
                            'No more results'
                        )}
                    </div>
                </div>
            ),
        })
    }

    return (
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            <div className="h-full deprecated-space-y-2">
                <Playlist
                    data-attr="session-recordings-playlist"
                    notebooksHref={urls.replay(ReplayTabs.Home, filters)}
                    embedded={!!notebookNode}
                    sections={sections}
                    headerActions={
                        <SessionRecordingsPlaylistTopSettings
                            filters={filters}
                            setFilters={setFilters}
                            type={type}
                            shortId={props.logicKey}
                        />
                    }
                    filterActions={
                        notebookNode || (!canMixFiltersAndPinned && !!logicProps.logicKey) ? null : (
                            <RecordingsUniversalFiltersEmbedButton
                                filters={filters}
                                setFilters={setFilters}
                                totalFiltersCount={totalFiltersCount}
                            />
                        )
                    }
                    loading={sessionRecordingsResponseLoading}
                    onScrollListEdge={(edge) => {
                        if (edge === 'top') {
                            maybeLoadSessionRecordings('newer')
                        } else {
                            maybeLoadSessionRecordings('older')
                        }
                    }}
                    listEmptyState={
                        type === 'collection' ? (
                            <CollectionEmptyState isSynthetic={isSynthetic} description={description} />
                        ) : (
                            <ListEmptyState />
                        )
                    }
                    onSelect={(item) => setSelectedRecordingId(item.id)}
                    activeItemId={activeSessionRecordingId}
                    content={({ activeItem }) =>
                        showContent && activeItem ? (
                            <SessionRecordingPlayer
                                playerKey={props.logicKey ?? 'playlist'}
                                sessionRecordingId={activeItem.id}
                                matchingEventsMatchType={matchingEventsMatchType}
                                playlistLogic={playlistLogic}
                                noBorder
                                pinned={!!pinnedRecordings.find((x) => x.id === activeItem.id)}
                                setPinned={
                                    props.onPinnedChange
                                        ? (pinned) => {
                                              if (!activeItem.id) {
                                                  return
                                              }
                                              props.onPinnedChange?.(activeItem, pinned)
                                          }
                                        : undefined
                                }
                            />
                        ) : (
                            <div className="mt-20">
                                <EmptyMessage
                                    title="No recording selected"
                                    description="Please select a recording from the list on the left"
                                    buttonText="Learn more about recordings"
                                    buttonTo="https://posthog.com/docs/user-guides/recordings"
                                />
                            </div>
                        )
                    }
                    filterContent={
                        <RecordingsUniversalFiltersEmbed
                            resetFilters={resetFilters}
                            filters={filters}
                            setFilters={setFilters}
                            totalFiltersCount={totalFiltersCount}
                            allowReplayHogQLFilters={allowHogQLFilters}
                            allowReplayGroupsFilters={allowReplayGroupsFilters}
                        />
                    }
                />
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
                <div className="flex flex-col gap-2">
                    <SessionRecordingsPlaylistTroubleshooting />
                </div>
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

/**
 * TODO add docs on how to enrich custom events with session_id and link to it from here
 */
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
