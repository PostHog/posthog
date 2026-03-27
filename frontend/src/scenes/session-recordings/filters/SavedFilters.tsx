import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { useState } from 'react'

import { IconCheck, IconPencil, IconShare, IconTrash, IconX } from '@posthog/icons'
import {
    LemonBadge,
    LemonButton,
    LemonInput,
    LemonTable,
    LemonTableColumn,
    LemonTableColumns,
    Tooltip,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { IconArrowUp } from 'lib/lemon-ui/icons'
import { isObject } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import {
    AccessControlLevel,
    AccessControlResourceType,
    PlaylistRecordingsCounts,
    RecordingUniversalFilters,
    ReplayTabs,
    SessionRecordingPlaylistType,
} from '~/types'

import { sessionRecordingSavedFiltersLogic } from '../filters/sessionRecordingSavedFiltersLogic'
import { playlistFiltersLogic } from '../playlist/playlistFiltersLogic'
import { updatePlaylist } from '../playlist/playlistUtils'
import { SavedFiltersEmptyState, SavedFiltersLoadingState } from './SavedFiltersStates'

export function isPlaylistRecordingsCounts(x: unknown): x is PlaylistRecordingsCounts {
    return isObject(x) && ('collection' in x || 'saved_filters' in x)
}

export function countColumn(): LemonTableColumn<SessionRecordingPlaylistType, 'recordings_counts'> {
    return {
        dataIndex: 'recordings_counts',
        title: 'Count',
        tooltip: 'Count of recordings in the saved filter',
        width: 0,
        render: function Render(recordings_counts) {
            if (!isPlaylistRecordingsCounts(recordings_counts)) {
                return null
            }

            const hasResults = recordings_counts.saved_filters?.count !== null

            const totalSavedFiltersCount = recordings_counts.saved_filters?.count || 0
            const unwatchedSavedFiltersCount =
                (recordings_counts.saved_filters?.count || 0) - (recordings_counts.saved_filters?.watched_count || 0)

            const lastRefreshedAt = recordings_counts.saved_filters?.last_refreshed_at

            const tooltip = (
                <div className="text-start">
                    {hasResults ? (
                        totalSavedFiltersCount > 0 ? (
                            unwatchedSavedFiltersCount > 0 ? (
                                <p>
                                    You have {unwatchedSavedFiltersCount} unwatched recordings to watch out of a total
                                    of {totalSavedFiltersCount}
                                    {recordings_counts.saved_filters?.has_more ? '+' : ''} that match these saved
                                    filters.
                                </p>
                            ) : (
                                <p>
                                    You have watched all of the {totalSavedFiltersCount} recordings that match these
                                    saved filters.
                                </p>
                            )
                        ) : (
                            <p>No results found for this saved filter.</p>
                        )
                    ) : (
                        <p>Counts have not yet been calculated for this saved filter.</p>
                    )}
                    {lastRefreshedAt ? (
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
                                    status={unwatchedSavedFiltersCount ? 'primary' : 'muted'}
                                    className="text-xs cursor-pointer"
                                    count={totalSavedFiltersCount}
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

export function SavedFilters({
    setFilters,
}: {
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element {
    const { filters, savedFilters, paginationSavedFilters, savedFiltersLoading } = useValues(
        sessionRecordingSavedFiltersLogic
    )
    const { deletePlaylist, setSavedPlaylistsFilters, setAppliedSavedFilter, loadSavedFilters } = useActions(
        sessionRecordingSavedFiltersLogic
    )
    const { setActiveFilterTab } = useActions(playlistFiltersLogic)

    const [editingId, setEditingId] = useState<string | null>(null)
    const [editName, setEditName] = useState('')

    const doSave = (shortId: string, newName: string): void => {
        const trimmed = newName.trim()
        if (!trimmed) {
            return
        }
        setEditingId(null)
        void updatePlaylist(shortId, { name: trimmed }).then(() => loadSavedFilters())
    }

    if (savedFiltersLoading && !filters.search) {
        return <SavedFiltersLoadingState />
    }

    if (savedFilters.results?.length === 0 && !filters.search) {
        return <SavedFiltersEmptyState />
    }

    const nameColumn = (): LemonTableColumn<SessionRecordingPlaylistType, 'name'> => {
        return {
            title: 'Name',
            dataIndex: 'name',
            render: function Render(name, { short_id, derived_name }) {
                const displayName = (name as string) || derived_name || 'Unnamed'

                if (editingId === short_id) {
                    return (
                        <div className="flex items-center gap-1">
                            <LemonInput
                                value={editName}
                                onChange={setEditName}
                                size="small"
                                autoFocus
                                fullWidth
                                stopPropagation
                                onPressEnter={() => doSave(short_id, editName)}
                                onClick={(e) => e.stopPropagation()}
                            />
                            <LemonButton
                                size="xsmall"
                                icon={<IconCheck />}
                                onClick={(e) => {
                                    e.stopPropagation()
                                    doSave(short_id, editName)
                                }}
                                tooltip="Save"
                                className="shrink-0"
                            />
                            <LemonButton
                                size="xsmall"
                                icon={<IconX />}
                                onClick={(e) => {
                                    e.stopPropagation()
                                    setEditingId(null)
                                }}
                                tooltip="Cancel"
                                className="shrink-0"
                            />
                        </div>
                    )
                }

                const filter = savedFilters.results.find(
                    (filter: SessionRecordingPlaylistType) => filter.short_id === short_id
                )
                return (
                    <div className="flex items-center gap-1 group">
                        <div
                            onClick={() => {
                                if (filter && filter.filters) {
                                    setFilters(filter.filters)
                                    setActiveFilterTab('filters')
                                    setAppliedSavedFilter(filter)
                                }
                            }}
                            className="cursor-pointer text-current hover:text-accent truncate"
                        >
                            {displayName}
                        </div>
                        <LemonButton
                            size="xsmall"
                            icon={<IconPencil />}
                            onClick={(e) => {
                                e.stopPropagation()
                                setEditName((name as string) || derived_name || '')
                                setEditingId(short_id)
                            }}
                            tooltip="Rename saved filter"
                            className="opacity-0 group-hover:opacity-100 shrink-0"
                        />
                    </div>
                )
            },
        }
    }

    const columns: LemonTableColumns<SessionRecordingPlaylistType> = [
        countColumn() as LemonTableColumn<SessionRecordingPlaylistType, keyof SessionRecordingPlaylistType | undefined>,
        nameColumn() as LemonTableColumn<SessionRecordingPlaylistType, keyof SessionRecordingPlaylistType | undefined>,
        {
            title: 'Share',
            width: 40,
            render: function Render(_, playlist) {
                return (
                    <LemonButton
                        onClick={() => {
                            const combinedURL = urls.absolute(
                                combineUrl(urls.replay(ReplayTabs.Home), { savedFilterId: playlist.short_id }).url
                            )
                            void copyToClipboard(combinedURL, 'link to ' + (playlist.name || playlist.derived_name))
                        }}
                        title="Copy link to saved filter"
                        tooltip="Copy link to saved filter"
                        icon={<IconShare />}
                        size="small"
                    />
                )
            },
        },
        {
            title: 'Delete',
            width: 40,
            render: function Render(_, playlist) {
                return (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.SessionRecording}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            status="danger"
                            onClick={() => {
                                deletePlaylist(playlist)
                                if (savedFilters.results?.length === 1) {
                                    setActiveFilterTab('filters')
                                }
                            }}
                            title="Delete saved filter"
                            tooltip="Delete saved filter"
                            icon={<IconTrash />}
                            size="small"
                        />
                    </AccessControlAction>
                )
            },
        },
    ]

    return (
        <>
            <LemonInput
                fullWidth
                className="mb-2"
                type="search"
                placeholder="Search for saved filters"
                onChange={(value) => setSavedPlaylistsFilters({ search: value || undefined })}
                value={filters.search || ''}
                stopPropagation={true}
            />
            <LemonTable
                dataSource={savedFilters.results}
                columns={columns}
                pagination={paginationSavedFilters}
                noSortingCancellation
            />
        </>
    )
}
