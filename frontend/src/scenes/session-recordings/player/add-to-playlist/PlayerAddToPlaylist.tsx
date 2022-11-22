import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { SessionRecordingPlaylistType } from '~/types'
import { LemonDialog } from 'lib/components/LemonDialog'
import { playerAddToPlaylistLogic } from 'scenes/session-recordings/player/add-to-playlist/playerAddToPlaylistLogic'
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
import { SessionRecordingPlayerLogicProps } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

interface PlaylistRelationRowProps {
    playlist: SessionRecordingPlaylistType
    sessionRecordingId: SessionRecordingPlayerLogicProps['sessionRecordingId']
    playerKey: SessionRecordingPlayerLogicProps['playerKey']
    isAlreadyOnPlaylist: boolean
    style: CSSProperties
}

const PlaylistRelationRow = ({
    isAlreadyOnPlaylist,
    playlist,
    style,
    sessionRecordingId,
    playerKey,
}: PlaylistRelationRowProps): JSX.Element => {
    const logic = playerAddToPlaylistLogic({
        sessionRecordingId,
        playerKey,
    })
    const { addToPlaylist, removeFromPlaylist } = useActions(logic)
    const { playlistWithActiveAPICall } = useValues(logic)

    return (
        <div data-attr="dashboard-list-item" style={style} className={clsx('flex items-center space-x-2')}>
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
                    isAlreadyOnPlaylist ? removeFromPlaylist(playlist) : addToPlaylist(playlist)
                }}
            >
                {isAlreadyOnPlaylist ? 'Added' : 'Add to playlist'}
            </LemonButton>
        </div>
    )
}

function AddRecordingToPlaylist({
    sessionRecordingId,
    playerKey,
    recordingStartTime,
}: SessionRecordingPlayerLogicProps): JSX.Element {
    const logic = playerAddToPlaylistLogic({ sessionRecordingId, playerKey, recordingStartTime })

    const { searchQuery, currentPlaylists, orderedPlaylists, playlistsResponseLoading, sessionPlayerMetaData } =
        useValues(logic)
    const { setSearchQuery } = useActions(logic)

    const renderItem: ListRowRenderer = ({ index: rowIndex, style }: ListRowProps): JSX.Element | null => {
        return (
            <PlaylistRelationRow
                key={rowIndex}
                playlist={orderedPlaylists[rowIndex]}
                sessionRecordingId={sessionRecordingId}
                playerKey={playerKey}
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
                <strong className="text-default">{sessionPlayerMetaData?.metadata?.playlists?.length || 0}</strong>
                {' static '}
                {pluralize(sessionPlayerMetaData?.metadata?.playlists?.length || 0, 'playlist', 'playlists', false)}
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
                            />
                        )}
                    </AutoSizer>
                )}
            </div>
        </div>
    )
}

export function openPlayerAddToPlaylistDialog(props: SessionRecordingPlayerLogicProps): void {
    LemonDialog.open({
        title: 'Add recording to static playlist',
        content: <AddRecordingToPlaylist {...props} />,
        width: '30rem',
        primaryButton: {
            children: 'Close',
            type: 'secondary',
        },
        tertiaryButton: {
            children: 'Add to new static playlist',
            type: 'secondary',
            onClick: () => {
                openPlayerNewPlaylistDialog({ ...props, defaultStatic: true })
            },
            keepOpen: true,
        },
    })
}
