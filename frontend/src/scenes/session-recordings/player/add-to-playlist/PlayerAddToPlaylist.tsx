import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { SessionRecordingPlaylistType, SessionRecordingType } from '~/types'
import { LemonDialog } from 'lib/components/LemonDialog'
import {
    playerAddToPlaylistLogic,
    PlayerAddToPlaylistLogicProps,
} from 'scenes/session-recordings/player/add-to-playlist/playerAddToPlaylistLogic'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { List, ListRowProps, ListRowRenderer } from 'react-virtualized/dist/es/List'
import { urls } from 'scenes/urls'
import { createPlaylist } from 'scenes/session-recordings/playlist/playlistUtils'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import clsx from 'clsx'
import { Link } from 'lib/components/Link'
import { pluralize } from 'lib/utils'
import { CSSProperties } from 'react'

interface PlaylistRelationRowProps {
    playlist: SessionRecordingPlaylistType
    sessionId: SessionRecordingType['id']
    playlistIds: string[]
    isHighlighted: boolean
    isAlreadyOnPlaylist: boolean
    style: CSSProperties
}

const PlaylistRelationRow = ({
    isHighlighted,
    isAlreadyOnPlaylist,
    playlist,
    sessionId,
    playlistIds,
    style,
}: PlaylistRelationRowProps): JSX.Element => {
    const logic = playerAddToPlaylistLogic({
        id: sessionId,
        playlists: playlistIds,
    })
    const { addToPlaylist, removeFromPlaylist } = useActions(logic)
    const { playlistWithActiveAPICall } = useValues(logic)

    return (
        <div
            data-attr="dashboard-list-item"
            style={style}
            className={clsx('flex items-center space-x-2', isHighlighted && 'highlighted')}
        >
            <Link to={urls.dashboard(playlist.id)}>{playlist.name || playlist.derived_name || 'Untitled'}</Link>
            <span className="grow" />
            <LemonButton
                type={isAlreadyOnPlaylist ? 'primary' : 'secondary'}
                loading={playlistWithActiveAPICall === playlist.id}
                disabled={!!playlistWithActiveAPICall}
                size="small"
                onClick={(e) => {
                    e.preventDefault()
                    isAlreadyOnPlaylist ? removeFromPlaylist(playlist.id) : addToPlaylist(playlist.id)
                }}
            >
                {isAlreadyOnPlaylist ? 'Added' : 'Add to playlist'}
            </LemonButton>
        </div>
    )
}

export function AddRecordingToPlaylist({ id, playlists }: PlayerAddToPlaylistLogicProps): JSX.Element {
    const logic = playerAddToPlaylistLogic({ id, playlists })

    const { searchQuery, currentPlaylists, orderedPlaylists, scrollIndex } = useValues(logic)
    const { setSearchQuery } = useActions(logic)

    const renderItem: ListRowRenderer = ({ index: rowIndex, style }: ListRowProps): JSX.Element | null => {
        return (
            <PlaylistRelationRow
                key={rowIndex}
                playlist={orderedPlaylists[rowIndex]}
                sessionId={id}
                playlistIds={playlists || []}
                isHighlighted={rowIndex === scrollIndex}
                isAlreadyOnPlaylist={currentPlaylists.some(
                    (currentPlaylist: SessionRecordingPlaylistType) =>
                        currentPlaylist.id === orderedPlaylists[rowIndex].id
                )}
                style={style}
            />
        )
    }

    return (
        <div className="space-y-2">
            <LemonInput
                data-attr="playlist-searchfield"
                type="search"
                fullWidth
                placeholder={`Search for playlists...`}
                value={searchQuery}
                onChange={(newValue) => setSearchQuery(newValue)}
            />
            <div className="text-muted-alt">
                This recording is referenced on <strong className="text-default">{playlists?.length}</strong>
                {' static'}
                {pluralize(playlists?.length || 0, 'playlist', 'playlists', false)}
            </div>
            <div style={{ minHeight: 420 }}>
                <AutoSizer>
                    {({ height, width }) => (
                        <List
                            width={width}
                            height={height}
                            rowCount={orderedPlaylists.length}
                            overscanRowCount={100}
                            rowHeight={40}
                            rowRenderer={renderItem}
                            scrollToIndex={scrollIndex}
                        />
                    )}
                </AutoSizer>
            </div>
        </div>
    )
}

export function openPlayerAddToPlaylistDialog({ id, playlists }: PlayerAddToPlaylistLogicProps): void {
    LemonDialog.open({
        title: 'Add recording to playlist',
        content: <AddRecordingToPlaylist id={id} playlists={playlists} />,
        width: 600,
        primaryButton: {
            children: 'Close',
            type: 'secondary',
        },
        tertiaryButton: {
            children: 'Add to new static playlist',
            type: 'secondary',
            onClick: () => {
                createPlaylist({ is_static: true }, false)
            },
        },
    })
}
