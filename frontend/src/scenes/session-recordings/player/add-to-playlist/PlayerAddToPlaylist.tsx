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
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import clsx from 'clsx'
import { Link } from 'lib/components/Link'
import { pluralize } from 'lib/utils'
import { CSSProperties } from 'react'
import { openPlayerNewPlaylistDialog } from 'scenes/session-recordings/player/new-playlist/PlayerNewPlaylist'
import { SpinnerOverlay } from 'lib/components/Spinner/Spinner'

interface PlaylistRelationRowProps {
    playlist: SessionRecordingPlaylistType
    recording: Pick<SessionRecordingType, 'id' | 'playlists' | 'start_time'>
    isHighlighted: boolean
    isAlreadyOnPlaylist: boolean
    style: CSSProperties
}

const PlaylistRelationRow = ({
    isHighlighted,
    isAlreadyOnPlaylist,
    playlist,
    recording,
    style,
}: PlaylistRelationRowProps): JSX.Element => {
    const logic = playerAddToPlaylistLogic({
        recording,
    })
    const { addRecordingToPlaylist, removeRecordingFromPlaylist } = useActions(logic)
    const { playlistWithActiveAPICall } = useValues(logic)

    return (
        <div
            data-attr="dashboard-list-item"
            style={style}
            className={clsx('flex items-center space-x-2', isHighlighted && 'highlighted')}
        >
            <Link to={urls.sessionRecordingPlaylist(playlist.short_id)}>
                {playlist.name || playlist.derived_name || 'Untitled'}
            </Link>
            <span className="grow" />
            <LemonButton
                type={isAlreadyOnPlaylist ? 'primary' : 'secondary'}
                loading={playlistWithActiveAPICall === playlist.id}
                disabled={!!playlistWithActiveAPICall}
                size="small"
                onClick={(e) => {
                    e.preventDefault()
                    isAlreadyOnPlaylist
                        ? removeRecordingFromPlaylist(recording, playlist)
                        : addRecordingToPlaylist(recording, playlist)
                }}
            >
                {isAlreadyOnPlaylist ? 'Added' : 'Add to playlist'}
            </LemonButton>
        </div>
    )
}

function AddRecordingToPlaylist({ recording }: PlayerAddToPlaylistLogicProps): JSX.Element {
    const logic = playerAddToPlaylistLogic({ recording })

    const {
        searchQuery,
        currentPlaylists,
        orderedPlaylists,
        scrollIndex,
        playlistsResponseLoading,
        filteredPlaylists,
    } = useValues(logic)
    const { setSearchQuery } = useActions(logic)

    console.log('currentPlaylists', recording, filteredPlaylists, currentPlaylists, orderedPlaylists)

    const renderItem: ListRowRenderer = ({ index: rowIndex, style }: ListRowProps): JSX.Element | null => {
        return (
            <PlaylistRelationRow
                key={rowIndex}
                playlist={orderedPlaylists[rowIndex]}
                recording={recording}
                isHighlighted={rowIndex === scrollIndex}
                isAlreadyOnPlaylist={currentPlaylists.some(
                    (currentPlaylist) => currentPlaylist.id === orderedPlaylists[rowIndex].id
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
                This recording is referenced on{' '}
                <strong className="text-default">{recording.playlists?.length || 0}</strong>
                {' static '}
                {pluralize(recording.playlists?.length || 0, 'playlist', 'playlists', false)}
            </div>
            <div style={{ minHeight: 420 }}>
                {playlistsResponseLoading ? (
                    <SpinnerOverlay />
                ) : (
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
                )}
            </div>
        </div>
    )
}

export function openPlayerAddToPlaylistDialog({ recording }: PlayerAddToPlaylistLogicProps): void {
    LemonDialog.open({
        title: 'Add recording to static playlist',
        content: <AddRecordingToPlaylist recording={recording} />,
        width: '30rem',
        primaryButton: {
            children: 'Close',
            type: 'secondary',
        },
        tertiaryButton: {
            children: 'Add to new static playlist',
            type: 'secondary',
            onClick: () => {
                openPlayerNewPlaylistDialog({ sessionRecordingId: recording.id, defaultStatic: true })
            },
            keepOpen: true,
        },
    })
}
