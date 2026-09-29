import { useActions, useValues } from 'kea'

import { IconCalendar, IconPin, IconPinFilled } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonTable } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { MemberSelect } from 'lib/components/MemberSelect'
import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'

import { AccessControlLevel, AccessControlResourceType, SessionRecordingPlaylistType } from '~/types'

import { BuiltInCollections } from './BuiltInCollections'
import { COLUMN_WIDTHS, countColumn, nameColumn, progressColumn, watchNextColumn } from './collectionColumns'
import { CollectionSectionHeading } from './CollectionSectionHeading'
import { SessionRecordingCollectionsEmptyState } from './SessionRecordingCollectionsEmptyState'
import { PLAYLISTS_PER_PAGE, sessionRecordingCollectionsLogic } from './sessionRecordingCollectionsLogic'

export function SessionRecordingCollections(): JSX.Element {
    const { playlists, playlistsLoading, builtInPlaylists, builtInPlaylistsLoading, filters, sorting, pagination } =
        useValues(sessionRecordingCollectionsLogic)
    const { setSavedPlaylistsFilters, updatePlaylist, duplicatePlaylist, deletePlaylist } = useActions(
        sessionRecordingCollectionsLogic
    )

    const columns: LemonTableColumns<SessionRecordingPlaylistType> = [
        {
            width: COLUMN_WIDTHS.leading,
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
        countColumn(),
        nameColumn(),
        {
            ...(createdByColumn<SessionRecordingPlaylistType>() as LemonTableColumn<
                SessionRecordingPlaylistType,
                keyof SessionRecordingPlaylistType | undefined
            >),
            width: COLUMN_WIDTHS.createdBy,
        },
        {
            title: 'Last modified',
            sorter: true,
            defaultSortOrder: -1,
            dataIndex: 'last_modified_at',
            width: COLUMN_WIDTHS.lastModified,
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
        progressColumn(),
        watchNextColumn(),
        {
            width: COLUMN_WIDTHS.actions,
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
            <BuiltInCollections playlists={builtInPlaylists} loading={builtInPlaylistsLoading} />

            <div className="border rounded overflow-hidden bg-surface-primary">
                <CollectionSectionHeading title="Your collections" description="Made by your team.">
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
                        size="small"
                    />
                    <MemberSelect
                        defaultLabel="Any creator"
                        value={filters.createdBy === 'All users' ? null : filters.createdBy}
                        onChange={(user) => setSavedPlaylistsFilters({ createdBy: user?.id || 'All users' })}
                    />
                    <LemonInput
                        type="search"
                        size="small"
                        placeholder="Search for collections"
                        onChange={(value) => setSavedPlaylistsFilters({ search: value || undefined })}
                        value={filters.search || ''}
                    />
                </CollectionSectionHeading>

                {!playlistsLoading && playlists.count < 1 ? (
                    <SessionRecordingCollectionsEmptyState />
                ) : (
                    <LemonTable
                        embedded
                        tableLayout="fixed"
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
