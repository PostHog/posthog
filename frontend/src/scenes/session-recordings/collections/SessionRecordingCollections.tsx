import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCalendar, IconPin, IconPinFilled } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonDivider, LemonInput, LemonTable, Link, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { MemberSelect } from 'lib/components/MemberSelect'
import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, SessionRecordingPlaylistType } from '~/types'

import { BuiltInCollections } from './BuiltInCollections'
import { getCollectionCounts, watchNextUrl } from './collectionUtils'
import { SessionRecordingCollectionsEmptyState } from './SessionRecordingCollectionsEmptyState'
import { PLAYLISTS_PER_PAGE, sessionRecordingCollectionsLogic } from './sessionRecordingCollectionsLogic'

function nameColumn(): LemonTableColumn<SessionRecordingPlaylistType, 'name'> {
    return {
        title: 'Name',
        dataIndex: 'name',
        render: function Render(name, { short_id, derived_name, description }) {
            return (
                <>
                    <Link
                        className={clsx('font-semibold', !name && 'italic')}
                        to={urls.replayPlaylist(short_id)}
                        data-attr="collections-scene-table-clicked-user-collection"
                    >
                        {name || derived_name || 'Unnamed'}
                    </Link>
                    {description ? <div className="truncate">{description}</div> : null}
                </>
            )
        },
    }
}

function countColumn(): LemonTableColumn<SessionRecordingPlaylistType, 'recordings_counts'> {
    return {
        dataIndex: 'recordings_counts',
        title: 'Count',
        tooltip: 'Count of recordings in the collection',
        width: 0,
        render: function Render(recordings_counts) {
            const counts = getCollectionCounts(recordings_counts)
            const tooltip = (
                <div className="text-start">
                    {counts ? (
                        counts.total && counts.total > 0 ? (
                            counts.unwatched > 0 ? (
                                <p>
                                    You have {counts.unwatched} unwatched recordings to watch out of a total of{' '}
                                    {counts.total} in this collection.
                                </p>
                            ) : (
                                <p>You have watched all of the {counts.total} recordings in this collection.</p>
                            )
                        ) : (
                            <p>No results found for this collection.</p>
                        )
                    ) : (
                        <p>Counts have not yet been calculated for this collection.</p>
                    )}
                </div>
            )

            return (
                <div className="flex items-center justify-start w-full h-full">
                    <Tooltip title={tooltip}>
                        {counts ? (
                            <span className="flex items-center gap-x-1 cursor-help">
                                <LemonBadge.Number
                                    status={counts.unwatched ? 'primary' : 'muted'}
                                    className="text-xs cursor-pointer"
                                    count={counts.total || 0}
                                    maxDigits={3}
                                    showZero={true}
                                />
                            </span>
                        ) : (
                            <span>
                                <LemonBadge status="muted" content="?" className="cursor-pointer" />
                            </span>
                        )}
                    </Tooltip>
                </div>
            )
        },
    }
}

export function SessionRecordingCollections(): JSX.Element {
    const { playlists, playlistsLoading, builtInPlaylists, filters, sorting, pagination } = useValues(
        sessionRecordingCollectionsLogic
    )
    const { setSavedPlaylistsFilters, updatePlaylist, duplicatePlaylist, deletePlaylist } = useActions(
        sessionRecordingCollectionsLogic
    )

    const columns: LemonTableColumns<SessionRecordingPlaylistType> = [
        {
            width: 0,
            dataIndex: 'pinned',
            render: function Render(pinned, { short_id }) {
                return (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.SessionRecording}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            onClick={() => updatePlaylist(short_id, { pinned: !pinned })}
                            icon={pinned ? <IconPinFilled /> : <IconPin />}
                        />
                    </AccessControlAction>
                )
            },
        },
        countColumn() as LemonTableColumn<SessionRecordingPlaylistType, keyof SessionRecordingPlaylistType | undefined>,
        nameColumn() as LemonTableColumn<SessionRecordingPlaylistType, keyof SessionRecordingPlaylistType | undefined>,
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
            defaultSortOrder: -1,
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
                const counts = getCollectionCounts(playlist.recordings_counts)
                return counts && counts.unwatched > 0 ? (
                    <LemonButton
                        size="small"
                        type="secondary"
                        to={watchNextUrl(playlist.short_id)}
                        data-attr="collections-scene-watch-next"
                    >
                        Watch next
                    </LemonButton>
                ) : null
            },
        },
        {
            width: 0,
            render: function Render(_, playlist) {
                return (
                    <More
                        overlay={
                            <>
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.SessionRecording}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <LemonButton
                                        onClick={() => duplicatePlaylist(playlist)}
                                        fullWidth
                                        data-attr="duplicate-playlist"
                                        loading={playlistsLoading}
                                    >
                                        Duplicate
                                    </LemonButton>
                                </AccessControlAction>

                                <LemonDivider />

                                <AccessControlAction
                                    resourceType={AccessControlResourceType.SessionRecording}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <LemonButton
                                        status="danger"
                                        onClick={() => deletePlaylist(playlist)}
                                        fullWidth
                                        loading={playlistsLoading}
                                    >
                                        Delete collection
                                    </LemonButton>
                                </AccessControlAction>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div className="flex flex-col gap-6">
            <BuiltInCollections playlists={builtInPlaylists} />

            <div className="flex flex-col gap-2">
                <div className="flex justify-between gap-2 items-center flex-wrap">
                    <div className="flex items-center gap-2">
                        <h3 className="mb-0">Your collections</h3>
                        <LemonInput
                            type="search"
                            placeholder="Search for collections"
                            onChange={(value) => setSavedPlaylistsFilters({ search: value || undefined })}
                            value={filters.search || ''}
                        />
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                        <LemonButton
                            data-attr="session-recording-playlist-pinned-filter"
                            active={filters.pinned}
                            size="small"
                            type="secondary"
                            status="alt"
                            center
                            onClick={() => setSavedPlaylistsFilters({ pinned: !filters.pinned })}
                            icon={filters.pinned ? <IconPinFilled /> : <IconPin />}
                        >
                            Pinned
                        </LemonButton>
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
                                        <IconCalendar />
                                        <span className="hide-when-small"> {key}</span>
                                    </>
                                )}
                                max={21}
                            />
                        </div>
                        <div className="flex items-center gap-2">
                            <span>Created by:</span>
                            <MemberSelect
                                value={filters.createdBy === 'All users' ? null : filters.createdBy}
                                onChange={(user) => setSavedPlaylistsFilters({ createdBy: user?.id || 'All users' })}
                            />
                        </div>
                    </div>
                </div>

                {!playlistsLoading && playlists.results.length < 1 ? (
                    <SessionRecordingCollectionsEmptyState />
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
                        nouns={['collection', 'collections']}
                    />
                )}
            </div>
        </div>
    )
}
