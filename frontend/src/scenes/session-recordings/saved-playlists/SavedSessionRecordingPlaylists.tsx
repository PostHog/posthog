import { teamLogic } from 'scenes/teamLogic'
import { useValues } from 'kea'
import { SessionRecordingsTabs, SessionRecordingPlaylistType } from '~/types'
import { savedSessionRecordingPlaylistsLogic } from './savedSessionRecordingPlaylistsLogic'
import { LemonTable, Link } from '@posthog/lemon-ui'
import { LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import { PushpinFilled, PushpinOutlined } from '@ant-design/icons'
import { urls } from 'scenes/urls'
import { createdAtColumn, createdByColumn } from 'lib/components/LemonTable/columnUtils'

export type SavedSessionRecordingPlaylistsProps = {
    tab: SessionRecordingsTabs.All | SessionRecordingsTabs.Yours | SessionRecordingsTabs.Pinned
}

export function SavedSessionRecordingPlaylists({ tab }: SavedSessionRecordingPlaylistsProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const logic = savedSessionRecordingPlaylistsLogic({ tab })
    const { playlists, playlistsLoading } = useValues(logic)

    const columns: LemonTableColumns<SessionRecordingPlaylistType> = [
        {
            width: 0,
            dataIndex: 'pinned',
            render: function Render(pinned, { id }) {
                return pinned ? (
                    <PushpinFilled onClick={() => alert('Clicked!')} style={{ cursor: 'pointer' }} />
                ) : (
                    <PushpinOutlined onClick={() => alert('Clicked!')} style={{ cursor: 'pointer' }} />
                )
            },
        },
        {
            title: 'Name',
            dataIndex: 'name',
            width: '40%',
            render: function Render(name, { id }) {
                return <Link to={urls.sessionRecordingPlaylist(id)}>{name || 'Untitled'}</Link>
            },
            sorter: (a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled'),
        },
        createdByColumn<SessionRecordingPlaylistType>() as LemonTableColumn<
            SessionRecordingPlaylistType,
            keyof SessionRecordingPlaylistType | undefined
        >,
        createdAtColumn<SessionRecordingPlaylistType>() as LemonTableColumn<
            SessionRecordingPlaylistType,
            keyof SessionRecordingPlaylistType | undefined
        >,
    ]

    return (
        <div>
            <LemonTable
                loading={playlistsLoading}
                columns={columns}
                dataSource={playlists.results}
                // pagination={pagination}
                noSortingCancellation
                // sorting={sorting}
                // onSort={(newSorting) =>
                //     setSavedInsightsFilters({
                //         order: newSorting ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}` : undefined,
                //     })
                // }
                rowKey="id"
                loadingSkeletonRows={15}
                nouns={['playlist', 'playlists']}
            />
        </div>
    )
}
