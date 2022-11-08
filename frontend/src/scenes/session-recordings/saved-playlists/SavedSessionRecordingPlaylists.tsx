import { teamLogic } from 'scenes/teamLogic'
import { useActions, useValues } from 'kea'
import { SessionRecordingsTabs, SessionRecordingPlaylistType } from '~/types'
import { savedSessionRecordingPlaylistsLogic } from './savedSessionRecordingPlaylistsLogic'
import { LemonDivider, LemonInput, LemonSelect, LemonTable, Link } from '@posthog/lemon-ui'
import { LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import { CalendarOutlined, PushpinFilled, PushpinOutlined } from '@ant-design/icons'
import { urls } from 'scenes/urls'
import { createdAtColumn, createdByColumn } from 'lib/components/LemonTable/columnUtils'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'

export type SavedSessionRecordingPlaylistsProps = {
    tab: SessionRecordingsTabs.All | SessionRecordingsTabs.Yours | SessionRecordingsTabs.Pinned
}

export function SavedSessionRecordingPlaylists({ tab }: SavedSessionRecordingPlaylistsProps): JSX.Element {
    const logic = savedSessionRecordingPlaylistsLogic({ tab })
    const { playlists, playlistsLoading, filters } = useValues(logic)
    const { setSavedPlaylistsFilters } = useActions(logic)
    const { meFirstMembers } = useValues(membersLogic)

    const columns: LemonTableColumns<SessionRecordingPlaylistType> = [
        {
            width: 0,
            dataIndex: 'pinned',
            render: function Render(pinned, { short_id }) {
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
            render: function Render(name, { short_id, description }) {
                return (
                    <>
                        <Link className="font-semibold" to={urls.sessionRecordingPlaylist(short_id)}>
                            {name || 'Untitled'}
                        </Link>
                        {description ? <div className="truncate">{description}</div> : null}
                    </>
                )
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
        <div className="space-y-4">
            <div className="flex justify-between gap-2 mb-2 items-center flex-wrap">
                <LemonInput
                    type="search"
                    placeholder="Search for playlists"
                    onChange={(value) => setSavedPlaylistsFilters({ search: value })}
                    value={filters.search || ''}
                />
                <div className="flex items-center gap-2 flex-wrap">
                    <div className="flex items-center gap-2">
                        <span>Last modified:</span>
                        <DateFilter
                            disabled={false}
                            dateFrom={filters.dateFrom}
                            dateTo={filters.dateTo}
                            onChange={(fromDate, toDate) =>
                                setSavedPlaylistsFilters({ dateFrom: fromDate, dateTo: toDate ?? undefined })
                            }
                            makeLabel={(key) => (
                                <>
                                    <CalendarOutlined />
                                    <span className="hide-when-small"> {key}</span>
                                </>
                            )}
                        />
                    </div>
                    {tab !== SessionRecordingsTabs.Yours ? (
                        <div className="flex items-center gap-2">
                            <span>Created by:</span>
                            <LemonSelect
                                size="small"
                                options={[
                                    { value: 'All users' as number | 'All users', label: 'All Users' },
                                    ...meFirstMembers.map((x) => ({
                                        value: x.user.id,
                                        label: x.user.first_name,
                                    })),
                                ]}
                                value={filters.createdBy}
                                onChange={(v: any): void => {
                                    setSavedPlaylistsFilters({ createdBy: v })
                                }}
                                dropdownMatchSelectWidth={false}
                            />
                        </div>
                    ) : null}
                </div>
            </div>

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
