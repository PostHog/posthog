import { useActions, useValues } from 'kea'
import { cloneElement } from 'react'
import { SessionRecordingsTabs, SessionRecordingPlaylistType } from '~/types'
import { PLAYLISTS_PER_PAGE, savedSessionRecordingPlaylistsLogic } from './savedSessionRecordingPlaylistsLogic'
import { LemonButton, LemonDivider, LemonInput, LemonSelect, LemonTable, Link } from '@posthog/lemon-ui'
import { LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import { CalendarOutlined, PushpinFilled, PushpinOutlined } from '@ant-design/icons'
import { urls } from 'scenes/urls'
import { createdByColumn } from 'lib/components/LemonTable/columnUtils'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { TZLabel } from '@posthog/apps-common'
import { SavedSessionRecordingPlaylistsEmptyState } from 'scenes/session-recordings/saved-playlists/SavedSessionRecordingPlaylistsEmptyState'
import clsx from 'clsx'
import { More } from 'lib/components/LemonButton/More'

export type SavedSessionRecordingPlaylistsProps = {
    tab: SessionRecordingsTabs.Playlists
}

export function SavedSessionRecordingPlaylists({ tab }: SavedSessionRecordingPlaylistsProps): JSX.Element {
    const logic = savedSessionRecordingPlaylistsLogic({ tab })
    const { playlists, playlistsLoading, filters, sorting, pagination } = useValues(logic)
    const { setSavedPlaylistsFilters, updatePlaylist, duplicatePlaylist, deletePlaylist } = useActions(logic)
    const { meFirstMembers } = useValues(membersLogic)

    const columns: LemonTableColumns<SessionRecordingPlaylistType> = [
        {
            width: 0,
            dataIndex: 'pinned',
            render: function Render(pinned, { short_id }) {
                return (
                    <LemonButton
                        size="small"
                        status="primary-alt"
                        onClick={() => updatePlaylist(short_id, { pinned: !pinned })}
                    >
                        {pinned ? <PushpinFilled /> : <PushpinOutlined />}
                    </LemonButton>
                )
            },
        },
        {
            title: 'Name',
            dataIndex: 'name',
            render: function Render(name, { short_id, derived_name, description }) {
                return (
                    <>
                        <Link
                            className={clsx('font-semibold', !name && 'italic')}
                            to={urls.sessionRecordingPlaylist(short_id)}
                        >
                            {name || derived_name || '(Untitled)'}
                        </Link>
                        {description ? <div className="truncate">{description}</div> : null}
                    </>
                )
            },
        },
        {
            ...(createdByColumn<SessionRecordingPlaylistType>() as LemonTableColumn<
                SessionRecordingPlaylistType,
                keyof SessionRecordingPlaylistType | undefined
            >),
            width: 0,
        },
        {
            title: 'Last modified',
            sorter: true,
            dataIndex: 'last_modified_at',
            width: 0,
            render: function Render(last_modified_at) {
                return (
                    <div>
                        {last_modified_at && typeof last_modified_at === 'string' && (
                            <TZLabel time={last_modified_at} />
                        )}
                    </div>
                )
            },
        },

        {
            width: 0,
            render: function Render(_, playlist) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    status="stealth"
                                    onClick={() => duplicatePlaylist(playlist)}
                                    fullWidth
                                    data-attr="duplicate-playlist"
                                    loading={playlistsLoading}
                                >
                                    Duplicate
                                </LemonButton>
                                <LemonDivider />

                                <LemonButton
                                    status="danger"
                                    onClick={() => deletePlaylist(playlist)}
                                    fullWidth
                                    loading={playlistsLoading}
                                >
                                    Delete playlist
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div className="space-y-4">
            <div className="flex justify-between gap-2 mb-2 items-center flex-wrap">
                <LemonInput
                    type="search"
                    placeholder="Search for playlists"
                    onChange={(value) => setSavedPlaylistsFilters({ search: value || undefined })}
                    value={filters.search || ''}
                />
                <div className="flex items-center gap-4 flex-wrap">
                    <div className="flex items-center gap-2">
                        <LemonButton
                            data-attr="session-recording-playlist-pinned-filter"
                            active={filters.pinned}
                            size="small"
                            type="secondary"
                            status="stealth"
                            center
                            onClick={() => setSavedPlaylistsFilters({ pinned: !filters.pinned })}
                            icon={cloneElement(filters.pinned ? <PushpinFilled /> : <PushpinOutlined />, {
                                className: 'text-base flex items-center',
                            })}
                        >
                            Pinned
                        </LemonButton>
                    </div>
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
                </div>
            </div>

            {!playlistsLoading && playlists.count < 1 ? (
                <SavedSessionRecordingPlaylistsEmptyState />
            ) : (
                <LemonTable
                    loading={playlistsLoading}
                    columns={columns}
                    dataSource={playlists.results}
                    pagination={pagination}
                    noSortingCancellation
                    sorting={sorting}
                    onSort={(newSorting) =>
                        setSavedPlaylistsFilters({
                            order: newSorting
                                ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                : undefined,
                        })
                    }
                    rowKey="id"
                    loadingSkeletonRows={PLAYLISTS_PER_PAGE}
                    nouns={['playlist', 'playlists']}
                />
            )}
        </div>
    )
}
