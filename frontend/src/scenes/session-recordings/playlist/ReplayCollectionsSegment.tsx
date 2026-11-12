import { useActions, useValues } from 'kea'

import { IconPin, IconPinFilled, IconPlus } from '@posthog/icons'
import { Badge, Button, Input, Item, ItemContent, ItemDescription, Skeleton, Text } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
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
            data-quill
            className="flex flex-col flex-1 min-h-0 border border-border rounded bg-background text-foreground overflow-hidden"
            data-attr="list-collections"
        >
            <div className="flex items-center gap-2 p-2 border-b border-border">
                <Input
                    type="search"
                    size="sm"
                    className="flex-1"
                    placeholder="Search collections"
                    value={filters.search || ''}
                    onChange={(event) => setSavedPlaylistsFilters({ search: event.target.value || undefined })}
                    data-attr="list-collections-search"
                />
                <AccessControlAction
                    resourceType={AccessControlResourceType.SessionRecording}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <Button
                        variant="primary"
                        onClick={() => void createCollection()}
                        loading={creating}
                        data-attr="list-collections-new"
                    >
                        <IconPlus />
                        New
                    </Button>
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
                    <Item variant="outline" tone="destructive" className="m-2">
                        <ItemContent>
                            <ItemDescription>
                                Couldn't load your collections. Refresh the page to try again.
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                ) : playlistsLoading && playlists.results.length === 0 ? (
                    <RowSkeletons count={4} />
                ) : playlists.results.length === 0 ? (
                    <Text size="xs" variant="muted" className="px-3 py-4 text-center">
                        {searching
                            ? 'No collections match your search.'
                            : 'No collections yet. Create one to group recordings.'}
                    </Text>
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
            <div className="flex items-center justify-between gap-2 px-3 py-1.5 border-t border-border text-xs">
                <span className="text-muted-foreground">
                    {playlists.count > playlists.results.length
                        ? `Showing ${playlists.results.length} of ${playlists.count}`
                        : ''}
                </span>
                <Button
                    variant="link"
                    size="inline"
                    render={<LinkPrimitive to={urls.replay(ReplayTabs.Playlists)} />}
                    data-attr="list-collections-manage"
                >
                    Manage collections
                </Button>
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
    const total = counts?.total || 0
    return (
        <Button
            size="row"
            left
            className="rounded-none"
            onClick={onClick}
            data-attr={playlist.is_synthetic ? 'list-collections-row-synthetic' : 'list-collections-row'}
        >
            {icon}
            <span className="truncate">{playlist.name || playlist.derived_name || 'Unnamed'}</span>
            {counts && (
                <Badge
                    variant={counts.unwatched ? 'info' : 'default'}
                    className="ml-auto group-hover/button:bg-fill-selected"
                >
                    {total > 999 ? '999+' : total}
                </Badge>
            )}
        </Button>
    )
}

function RowSkeletons({ count }: { count: number }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 p-2">
            {Array.from({ length: count }, (_, i) => (
                <Skeleton key={i} className="h-7" />
            ))}
        </div>
    )
}
