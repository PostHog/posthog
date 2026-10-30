import { useActions, useValues } from 'kea'

import { IconPin, IconPinFilled, IconPlus } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonInput, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, ReplayTabs, SessionRecordingPlaylistType } from '~/types'

import { BUILT_IN_COLLECTION_ICONS } from '../collections/builtInCollectionIcons'
import { CollectionSectionHeading } from '../collections/CollectionSectionHeading'
import { getCollectionCounts } from '../collections/collectionUtils'
import { sessionRecordingCollectionsLogic } from '../collections/sessionRecordingCollectionsLogic'
import { useNewCollection } from '../collections/useNewCollection'
import { ReplayCollectionView } from './ReplayCollectionView'
import { replayListColumnLogic } from './replayListColumnLogic'

export function ReplayCollectionsSegment({ logicKey }: { logicKey: string }): JSX.Element {
    const { playlists, playlistsLoading, loadPlaylistsFailed, builtInPlaylists, builtInPlaylistsLoading, filters } =
        useValues(sessionRecordingCollectionsLogic)
    const { setSavedPlaylistsFilters } = useActions(sessionRecordingCollectionsLogic)
    const { openCollectionShortId } = useValues(replayListColumnLogic({ logicKey }))
    const { openCollection } = useActions(replayListColumnLogic({ logicKey }))
    const { createCollection, creating } = useNewCollection()
    const searching = !!filters.search

    if (openCollectionShortId) {
        return <ReplayCollectionView shortId={openCollectionShortId} logicKey={logicKey} />
    }

    return (
        <div
            className="flex flex-col flex-1 min-h-0 border rounded bg-surface-primary overflow-hidden"
            data-attr="list-collections"
        >
            <div className="flex items-center gap-2 p-2 border-b">
                <LemonInput
                    type="search"
                    size="small"
                    className="flex-1"
                    placeholder="Search collections"
                    value={filters.search || ''}
                    onChange={(value) => setSavedPlaylistsFilters({ search: value || undefined })}
                    data-attr="list-collections-search"
                />
                <AccessControlAction
                    resourceType={AccessControlResourceType.SessionRecording}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconPlus />}
                        onClick={() => void createCollection()}
                        loading={creating}
                        data-attr="list-collections-new"
                    >
                        New
                    </LemonButton>
                </AccessControlAction>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto">
                {!searching && (
                    <>
                        <CollectionSectionHeading title="Built-in" description="Kept up to date by PostHog." />
                        {builtInPlaylistsLoading && builtInPlaylists.length === 0 ? (
                            <RowSkeletons count={4} />
                        ) : (
                            builtInPlaylists.map((playlist) => (
                                <CollectionRow
                                    key={playlist.short_id}
                                    playlist={playlist}
                                    icon={BUILT_IN_COLLECTION_ICONS[playlist.short_id]}
                                    onClick={() => openCollection(playlist.short_id)}
                                />
                            ))
                        )}
                    </>
                )}
                <CollectionSectionHeading title="Your collections" description="Made by your team." />
                {loadPlaylistsFailed ? (
                    <LemonBanner type="error" className="m-2">
                        Couldn't load your collections. Refresh the page to try again.
                    </LemonBanner>
                ) : playlistsLoading && playlists.results.length === 0 ? (
                    <RowSkeletons count={4} />
                ) : playlists.results.length === 0 ? (
                    <p className="text-secondary text-xs m-0 px-3 py-4 text-center">
                        {searching
                            ? 'No collections match your search.'
                            : 'No collections yet. Create one to group recordings.'}
                    </p>
                ) : (
                    playlists.results.map((playlist) => (
                        <CollectionRow
                            key={playlist.short_id}
                            playlist={playlist}
                            icon={playlist.pinned ? <IconPinFilled /> : <IconPin />}
                            onClick={() => openCollection(playlist.short_id)}
                        />
                    ))
                )}
            </div>
            <div className="flex items-center justify-between gap-2 px-3 py-1.5 border-t text-xs">
                <span className="text-secondary">
                    {playlists.count > playlists.results.length
                        ? `Showing ${playlists.results.length} of ${playlists.count}`
                        : ''}
                </span>
                <Link to={urls.replay(ReplayTabs.Playlists)} data-attr="list-collections-manage">
                    Manage collections
                </Link>
            </div>
        </div>
    )
}

function CollectionRow({
    playlist,
    icon,
    onClick,
}: {
    playlist: SessionRecordingPlaylistType
    icon?: JSX.Element
    onClick: () => void
}): JSX.Element {
    const counts = getCollectionCounts(playlist.recordings_counts)
    return (
        <LemonButton
            fullWidth
            size="small"
            className="rounded-none"
            icon={icon}
            onClick={onClick}
            sideIcon={
                counts ? (
                    <LemonBadge.Number
                        count={counts.total || 0}
                        status={counts.unwatched ? 'primary' : 'muted'}
                        size="small"
                        maxDigits={3}
                        showZero
                    />
                ) : undefined
            }
            data-attr={playlist.is_synthetic ? 'list-collections-row-synthetic' : 'list-collections-row'}
        >
            <span className="truncate font-normal">{playlist.name || playlist.derived_name || 'Unnamed'}</span>
        </LemonButton>
    )
}

function RowSkeletons({ count }: { count: number }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 p-2">
            {Array.from({ length: count }, (_, i) => (
                <LemonSkeleton key={i} className="h-7" />
            ))}
        </div>
    )
}
