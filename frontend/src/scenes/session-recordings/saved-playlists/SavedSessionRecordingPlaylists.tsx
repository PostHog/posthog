import { IconCalendar, IconPin, IconPinFilled } from '@posthog/icons'
import {
    LemonBadge,
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonTable,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { MemberSelect } from 'lib/components/MemberSelect'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconArrowUp } from 'lib/lemon-ui/icons'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { isObject } from 'lib/utils'
import { SavedSessionRecordingPlaylistsEmptyState } from 'scenes/session-recordings/saved-playlists/SavedSessionRecordingPlaylistsEmptyState'
import { urls } from 'scenes/urls'

import { PlaylistRecordingsCounts, ReplayTabs, SessionRecordingPlaylistType } from '~/types'

import { PLAYLISTS_PER_PAGE, savedSessionRecordingPlaylistsLogic } from './savedSessionRecordingPlaylistsLogic'

export type SavedSessionRecordingPlaylistsProps = {
    tab: ReplayTabs.Playlists
}

function nameColumn(): LemonTableColumn<SessionRecordingPlaylistType, 'name'> {
    return {
        title: 'Name',
        dataIndex: 'name',
        render: function Render(name, { short_id, derived_name, description }) {
            return (
                <>
                    <Link className={clsx('font-semibold', !name && 'italic')} to={urls.replayPlaylist(short_id)}>
                        {name || derived_name || 'Unnamed'}
                    </Link>
                    {description ? <div className="truncate">{description}</div> : null}
                </>
            )
        },
    }
}

export function countColumn({
    showCountColumn,
}: {
    showCountColumn: boolean
}): LemonTableColumn<SessionRecordingPlaylistType, 'recordings_counts'> {
    return {
        dataIndex: 'recordings_counts',
        title: 'Count',
        tooltip: 'Count of recordings in the collection',
        isHidden: !showCountColumn,
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
            const totalSavedFiltersCount = recordings_counts.saved_filters?.count || 0
            const unwatchedSavedFiltersCount =
                (recordings_counts.saved_filters?.count || 0) - (recordings_counts.saved_filters?.watched_count || 0)

            // we don't allow both saved filters and pinned anymore
            const isShowingSavedFilters = hasResults && !totalPinnedCount
            const totalCount = isShowingSavedFilters ? totalSavedFiltersCount : totalPinnedCount
            const unwatchedCount = isShowingSavedFilters ? unwatchedSavedFiltersCount : unwatchedPinnedCount
            // if we're showing saved filters, then we might have more results
            const hasMoreResults = isShowingSavedFilters && recordings_counts.saved_filters?.has_more

            const lastRefreshedAt = isShowingSavedFilters ? recordings_counts.saved_filters?.last_refreshed_at : null

            const description = isShowingSavedFilters ? 'that match these saved filters' : 'in this collection'

            const tooltip = (
                <div className="text-start">
                    {hasResults ? (
                        totalCount > 0 ? (
                            unwatchedCount > 0 ? (
                                <p>
                                    You have {unwatchedCount} unwatched recordings to watch out of a total of{' '}
                                    {totalCount}
                                    {hasMoreResults ? '+' : ''} {description}.
                                </p>
                            ) : (
                                <p>
                                    You have watched all of the {totalCount} recordings {description}.
                                </p>
                            )
                        ) : (
                            <p>No results found for this playlist.</p>
                        )
                    ) : (
                        <p>Counts have not yet been calculated for this playlist.</p>
                    )}
                    {isShowingSavedFilters && lastRefreshedAt ? (
                        <div className="text-xs items-center flex flex-row gap-x-1">
                            Last refreshed: <TZLabel time={lastRefreshedAt} showPopover={false} />
                        </div>
                    ) : null}
                </div>
            )

            return (
                <div className="flex items-center justify-start w-full h-full">
                    <Tooltip title={tooltip}>
                        {hasResults ? (
                            <span className="flex items-center deprecated-space-x-1">
                                <LemonBadge.Number
                                    status={unwatchedCount ? 'primary' : 'muted'}
                                    className="text-xs cursor-pointer"
                                    count={totalCount}
                                    maxDigits={3}
                                    showZero={true}
                                    forcePlus={
                                        !!recordings_counts.saved_filters?.count &&
                                        !!recordings_counts.saved_filters?.has_more
                                    }
                                />
                                {recordings_counts.saved_filters?.increased ? <IconArrowUp /> : null}
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

export function SavedSessionRecordingPlaylists({ tab }: SavedSessionRecordingPlaylistsProps): JSX.Element {
    const logic = savedSessionRecordingPlaylistsLogic({ tab })
    const { playlists, playlistsLoading, filters, sorting, pagination } = useValues(logic)
    const { setSavedPlaylistsFilters, updatePlaylist, duplicatePlaylist, deletePlaylist } = useActions(logic)

    const showCountColumn = useFeatureFlag('SESSION_RECORDINGS_PLAYLIST_COUNT_COLUMN')

    const columns: LemonTableColumns<SessionRecordingPlaylistType> = [
        {
            width: 0,
            dataIndex: 'pinned',
            render: function Render(pinned, { short_id }) {
                return (
                    <LemonButton
                        size="small"
                        onClick={() => updatePlaylist(short_id, { pinned: !pinned })}
                        icon={pinned ? <IconPinFilled /> : <IconPin />}
                    />
                )
            },
        },
        countColumn({ showCountColumn }) as LemonTableColumn<
            SessionRecordingPlaylistType,
            keyof SessionRecordingPlaylistType | undefined
        >,
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
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
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
                                    Delete collection
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div className="deprecated-space-y-4">
            <LemonBanner type="info" dismissKey="session-recordings-playlists-banner">
                We've made some updates!
                <br />
                <p className="font-normal">
                    Playlists used to combine saved filters and pinned recordings, but that sometimes led to confusion.
                    Now, they are handled separately:
                    <ul className="list-disc list-inside">
                        <li>
                            <Link to={`${urls.replay(ReplayTabs.Home)}?showFilters=true&filtersTab=saved`}>
                                Saved Filters
                            </Link>{' '}
                            stay with filters.
                        </li>
                        <li>Collections are simple recording lists — no filters involved.</li>
                    </ul>
                    More predictable, less messy!
                </p>
            </LemonBanner>
            <div className="flex justify-between gap-2 mb-2 items-center flex-wrap">
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
