import { LemonCard, LemonTag, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SessionRecordingPlaylistType } from '~/types'

import { getCollectionCounts, watchNextUrl } from './collectionUtils'

export function BuiltInCollections({ playlists }: { playlists: SessionRecordingPlaylistType[] }): JSX.Element | null {
    if (playlists.length === 0) {
        return null
    }
    return (
        <div className="flex flex-col gap-2">
            <h3 className="mb-0">Built-in</h3>
            <div className="flex flex-wrap gap-2 items-stretch">
                {playlists.map((playlist) => {
                    const counts = getCollectionCounts(playlist.recordings_counts)
                    return (
                        <LemonCard
                            key={playlist.short_id}
                            hoverEffect={false}
                            className="flex flex-col gap-0.5 p-3 w-64"
                        >
                            <Link
                                to={urls.replayPlaylist(playlist.short_id)}
                                className="font-semibold"
                                data-attr="collections-scene-table-clicked-synthetic-collection"
                            >
                                {playlist.name}
                            </Link>
                            <div className="flex items-center gap-2">
                                <span className="text-xl font-bold leading-tight">
                                    {counts ? (counts.total ?? 0) : '?'}
                                </span>
                                {counts && counts.unwatched > 0 ? (
                                    <Link to={watchNextUrl(playlist.short_id)} data-attr="collections-scene-watch-next">
                                        <LemonTag type="primary" size="small">
                                            {counts.unwatched} unwatched
                                        </LemonTag>
                                    </Link>
                                ) : null}
                            </div>
                            {playlist.description ? (
                                <span className="text-xs text-secondary">{playlist.description}</span>
                            ) : null}
                        </LemonCard>
                    )
                })}
            </div>
        </div>
    )
}
