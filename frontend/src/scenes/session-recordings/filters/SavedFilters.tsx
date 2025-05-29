import { LemonButton, LemonTable, LemonTableColumn, LemonTableColumns } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { More } from 'lib/lemon-ui/LemonButton/More'

import { RecordingUniversalFilters, ReplayTabs, SessionRecordingPlaylistType } from '~/types'

import { playlistLogic } from '../playlist/playlistLogic'
import { countColumn } from '../saved-playlists/SavedSessionRecordingPlaylists'
import { SavedSessionRecordingPlaylistsEmptyState } from '../saved-playlists/SavedSessionRecordingPlaylistsEmptyState'
import { savedSessionRecordingPlaylistsLogic } from '../saved-playlists/savedSessionRecordingPlaylistsLogic'

export function SavedFilters({
    setFilters,
}: {
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element {
    const savedFiltersLogic = savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Playlists })
    const { savedFilters, savedFiltersLoading, pagination } = useValues(savedFiltersLogic)
    const { deletePlaylist } = useActions(savedFiltersLogic)
    const { setActiveFilterTab } = useActions(playlistLogic)

    const showCountColumn = useFeatureFlag('SESSION_RECORDINGS_PLAYLIST_COUNT_COLUMN')

    if (savedFiltersLoading || savedFilters.results?.length === 0) {
        return <SavedSessionRecordingPlaylistsEmptyState />
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
            width: 0,
            render: function Render(_, playlist) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    status="danger"
                                    onClick={() => {
                                        deletePlaylist(playlist)
                                        if (savedFilters.results?.length === 1) {
                                            setActiveFilterTab('filters')
                                        }
                                    }}
                                    fullWidth
                                    loading={savedFiltersLoading}
                                >
                                    Delete saved filter
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <LemonTable
            loading={savedFiltersLoading}
            dataSource={savedFilters.results}
            columns={columns}
            pagination={pagination}
            noSortingCancellation
        />
    )
}
