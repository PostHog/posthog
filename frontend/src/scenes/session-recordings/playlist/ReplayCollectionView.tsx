import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'

import { IconArrowLeft, IconExternal, IconPlus } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { urls } from 'scenes/urls'

import { BUILT_IN_COLLECTION_ICONS } from '../collections/builtInCollectionIcons'
import { AddRecordingsToCollectionModal } from './AddRecordingsToCollectionModal'
import { Playlist } from './Playlist'
import { replayCollectionViewLogic } from './replayCollectionViewLogic'
import { replayListColumnLogic } from './replayListColumnLogic'
import { SessionRecordingPlaylistLogicProps, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { sessionRecordingsPlaylistSceneLogic } from './sessionRecordingsPlaylistSceneLogic'

export function ReplayCollectionView({ shortId, logicKey }: { shortId: string; logicKey: string }): JSX.Element {
    const columnLogic = replayListColumnLogic({ logicKey })
    const { closeCollection } = useActions(columnLogic)
    const sceneLogic = sessionRecordingsPlaylistSceneLogic({ shortId })
    const { playlist, playlistLoading, pinnedRecordings } = useValues(sceneLogic)
    const { onPinnedChange, setAddRecordingsModalOpen } = useActions(sceneLogic)

    const listProps: SessionRecordingPlaylistLogicProps = {
        logicKey: shortId,
        type: 'collection',
        onlyPinned: true,
        autoPlay: false,
        updateSearchParams: false,
        pinnedRecordings: pinnedRecordings ?? [],
        onPinnedChange,
        analyticsSource: 'replay-list-collection',
    }
    useMountedLogic(
        replayCollectionViewLogic({ shortId, listProps, mainListProps: columnLogic.props.playlistLogicProps })
    )
    const failed = !playlist && !playlistLoading

    return (
        <div className="flex flex-col flex-1 min-h-0 gap-2" data-attr="list-collection-view">
            <div className="flex items-center gap-1">
                <LemonButton
                    size="small"
                    icon={<IconArrowLeft />}
                    onClick={closeCollection}
                    tooltip="Back to collections"
                    aria-label="Back to collections"
                    data-attr="list-collection-back"
                />
                {playlist ? (
                    <span className="flex items-center gap-1.5 min-w-0 flex-1 text-sm font-semibold">
                        {BUILT_IN_COLLECTION_ICONS[playlist.short_id]}
                        <span className="truncate">{playlist.name || playlist.derived_name || 'Unnamed'}</span>
                        <LemonBadge.Number count={pinnedRecordings?.length ?? 0} size="small" status="muted" showZero />
                    </span>
                ) : failed ? (
                    <span className="flex-1 text-sm font-semibold">Collection</span>
                ) : (
                    <LemonSkeleton className="h-5 flex-1" />
                )}
                {playlist && !playlist.is_synthetic && (
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconPlus />}
                        onClick={() => setAddRecordingsModalOpen(true)}
                        data-attr="list-collection-add-recordings"
                    >
                        Add
                    </LemonButton>
                )}
                <LemonButton
                    size="small"
                    icon={<IconExternal />}
                    to={urls.replayPlaylist(shortId)}
                    tooltip="Open collection page"
                    aria-label="Open collection page"
                    data-attr="list-collection-open-page"
                />
            </div>
            {failed ? (
                <LemonBanner type="error">Couldn't load this collection. Refresh the page to try again.</LemonBanner>
            ) : (
                <BindLogic logic={sessionRecordingsPlaylistLogic} props={listProps}>
                    <Playlist
                        type="collection"
                        logicKey={shortId}
                        isSynthetic={playlist?.is_synthetic}
                        description={playlist?.description}
                        watchLayout
                    />
                </BindLogic>
            )}
            {playlist && !playlistLoading && (
                <BindLogic logic={sessionRecordingsPlaylistSceneLogic} props={{ shortId }}>
                    <AddRecordingsToCollectionModal />
                </BindLogic>
            )}
        </div>
    )
}
