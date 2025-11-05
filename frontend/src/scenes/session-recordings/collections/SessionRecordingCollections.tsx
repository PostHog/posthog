import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCalendar, IconPin, IconPinFilled } from '@posthog/icons'
import {
    LemonBadge,
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonTable,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { MemberSelect } from 'lib/components/MemberSelect'
import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { isObject } from 'lib/utils'
import { urls } from 'scenes/urls'

import {
    AccessControlLevel,
    AccessControlResourceType,
    PlaylistRecordingsCounts,
    SessionRecordingPlaylistType,
} from '~/types'

import { SessionRecordingCollectionsEmptyState } from './SessionRecordingCollectionsEmptyState'
import { PLAYLISTS_PER_PAGE, sessionRecordingCollectionsLogic } from './sessionRecordingCollectionsLogic'

function nameColumn(): LemonTableColumn<SessionRecordingPlaylistType, 'name'> {
    return {
        title: 'Name',
        dataIndex: 'name',
        render: function Render(name, { short_id, derived_name, description, is_synthetic }) {
            return (
                <>
                    <Link
                        className={clsx('font-semibold', !name && 'italic')}
                        to={urls.replayPlaylist(short_id)}
                        data-attr={
                            is_synthetic
                                ? 'collections-scene-table-clicked-synthetic-collection'
                                : 'collections-scene-table-clicked-user-collection'
                        }
                    >
                        {name || derived_name || 'Unnamed'}
                    </Link>
                    {description ? <div className="truncate">{description}</div> : null}
                </>
            )
        },
    }
}

export function countColumn(): LemonTableColumn<SessionRecordingPlaylistType, 'recordings_counts'> {
    return {
        dataIndex: 'recordings_counts',
        title: 'Count',
        tooltip: 'Count of recordings in the collection',
        width: 0,
        render: function Render(recordings_counts) {
            if (!isPlaylistRecordingsCounts(recordings_counts)) {
                return null
            }

            const hasResults =
                recordings_counts.collection.count !== null || recordings_counts.saved_filters?.count !== null

            const totalPinnedCount: number | null = recordings_counts.collection.count
            const unwatchedPinnedCount =
                (recordings_counts.collection.count || 0) - (recordings_counts.collection.watched_count || 0)

            const tooltip = (
                <div className="text-start">
                    {hasResults ? (
                        totalPinnedCount > 0 ? (
                            unwatchedPinnedCount > 0 ? (
                                <p>
                                    You have {unwatchedPinnedCount} unwatched recordings to watch out of a total of{' '}
                                    {totalPinnedCount} in this collection.
                                </p>
                            ) : (
                                <p>You have watched all of the {totalPinnedCount} recordings in this collection.</p>
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
                        {hasResults ? (
                            <span className="flex items-center gap-x-1 cursor-help">
                                <LemonBadge.Number
                                    status={unwatchedPinnedCount ? 'primary' : 'muted'}
                                    className="text-xs cursor-pointer"
                                    count={totalPinnedCount || 0}
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

export function isPlaylistRecordingsCounts(x: unknown): x is PlaylistRecordingsCounts {
    return isObject(x) && ('collection' in x || 'saved_filters' in x)
}

export function SessionRecordingCollections(): JSX.Element {
    const { playlists, playlistsLoading, filters, sorting, pagination } = useValues(sessionRecordingCollectionsLogic)
    const { setSavedPlaylistsFilters, updatePlaylist, duplicatePlaylist, deletePlaylist } = useActions(
        sessionRecordingCollectionsLogic
    )

    const columns: LemonTableColumns<SessionRecordingPlaylistType> = [
        {
            width: 0,
            dataIndex: 'pinned',
            render: function Render(pinned, { is_synthetic, short_id }) {
                // Don't show pin button for synthetic playlists
                if (is_synthetic) {
                    return null
                }
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
                // Don't show actions menu for synthetic playlists
                if (playlist.is_synthetic) {
                    return null
                }
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
        <>
            <div className="flex justify-between gap-2 items-center flex-wrap">
                <LemonInput
                    type="search"
                    placeholder="Search for collections"
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
                            status="alt"
                            center
                            onClick={() => setSavedPlaylistsFilters({ pinned: !filters.pinned })}
                            icon={filters.pinned ? <IconPinFilled /> : <IconPin />}
                        >
                            Pinned
                        </LemonButton>

                        <div className="flex items-center gap-2">
                            <span>Collection type:</span>
                            <LemonSelect
                                data-attr="session-recording-collections-type-select"
                                value={filters.collectionType}
                                onSelect={(value) => {
                                    setSavedPlaylistsFilters({ collectionType: value })
                                }}
                                options={[
                                    {
                                        label: 'All',
                                        value: null,
                                    },
                                    {
                                        label: 'Custom',
                                        value: 'custom',
                                    },
                                    {
                                        label: 'Automatic',
                                        value: 'synthetic',
                                    },
                                ]}
                            />
                        </div>
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

            {!playlistsLoading && playlists.count < 1 ? (
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
        </>
    )
}
