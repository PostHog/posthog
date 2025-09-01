import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconShare, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable, LemonTableColumn, LemonTableColumns } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { RecordingUniversalFilters, ReplayTabs, SessionRecordingPlaylistType } from '~/types'

import { playlistLogic } from '../playlist/playlistLogic'
import { countColumn } from '../saved-playlists/SavedSessionRecordingPlaylists'
import { savedSessionRecordingPlaylistsLogic } from '../saved-playlists/savedSessionRecordingPlaylistsLogic'
import { SavedFiltersEmptyState, SavedFiltersLoadingState } from './SavedFiltersStates'

export function SavedFilters({
    setFilters,
}: {
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element {
    const savedFiltersLogic = savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Home })
    const { savedFilters, paginationSavedFilters, savedFiltersSearch, savedFiltersLoading } =
        useValues(savedFiltersLogic)
    const { deletePlaylist, setSavedFiltersSearch, setAppliedSavedFilter } = useActions(savedFiltersLogic)
    const { setActiveFilterTab } = useActions(playlistLogic)

    const showCountColumn = useFeatureFlag('SESSION_RECORDINGS_PLAYLIST_COUNT_COLUMN')

    if (savedFiltersLoading && !savedFiltersSearch) {
        return <SavedFiltersLoadingState />
    }

    if (savedFilters.results?.length === 0 && !savedFiltersSearch) {
        return <SavedFiltersEmptyState />
    }

    const nameColumn = (): LemonTableColumn<SessionRecordingPlaylistType, 'name'> => {
        return {
            title: 'Name',
            dataIndex: 'name',
            render: function Render(name, { short_id, derived_name }) {
                const filter = savedFilters.results.find((filter) => filter.short_id === short_id)
                return (
                    <>
                        <div
                            onClick={() => {
                                if (filter && filter.filters) {
                                    setFilters(filter.filters)
                                    setActiveFilterTab('filters')
                                    setAppliedSavedFilter(filter)
                                }
                            }}
                            className="cursor-pointer text-current hover:text-accent"
                        >
                            {name || derived_name || 'Unnamed'}
                        </div>
                    </>
                )
            },
        }
    }

    const columns: LemonTableColumns<SessionRecordingPlaylistType> = [
        countColumn({ showCountColumn }) as LemonTableColumn<
            SessionRecordingPlaylistType,
            keyof SessionRecordingPlaylistType | undefined
        >,
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
                onChange={setSavedFiltersSearch}
                value={savedFiltersSearch}
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
