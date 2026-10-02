import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonMenuItems, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu'
import { sessionRecordingCollectionsLogic } from 'scenes/session-recordings/collections/sessionRecordingCollectionsLogic'
import { sessionRecordingSavedFiltersLogic } from 'scenes/session-recordings/filters/sessionRecordingSavedFiltersLogic'
import { urls } from 'scenes/urls'

import { ReplayTabs } from '~/types'

export function NavSessionReplayMenu(): JSX.Element {
    const { savedFilters, savedFiltersLoading, loadSavedFiltersFailed } = useValues(sessionRecordingSavedFiltersLogic)
    const { loadSavedFilters } = useActions(sessionRecordingSavedFiltersLogic)
    const { playlists, playlistsLoading, loadPlaylistsFailed } = useValues(sessionRecordingCollectionsLogic)
    const { loadPlaylists } = useActions(sessionRecordingCollectionsLogic)

    const items: LemonMenuItems = [
        {
            label: 'Saved filters',
            items: [
                ...(savedFiltersLoading
                    ? [{ label: 'Loading saved filters…', disabledReason: 'Loading' }]
                    : loadSavedFiltersFailed
                      ? [
                            {
                                label: 'Could not load saved filters. Reopen this menu to retry.',
                                disabledReason: 'Could not load saved filters',
                            },
                        ]
                      : savedFilters.results.map((filter) => ({
                            label: filter.name || filter.derived_name || 'Unnamed',
                            // Replay reads savedFilterId on mount, so a full navigation applies it even from Replay home.
                            to: urls.absolute(
                                combineUrl(urls.replay(ReplayTabs.Home), { savedFilterId: filter.short_id }).url
                            ),
                            disableClientSideRouting: true,
                        }))),
                {
                    label: 'All saved filters',
                    to: `${urls.replay(ReplayTabs.Home)}?showFilters=true&filtersTab=saved`,
                },
            ],
        },
        {
            label: 'Collections',
            items: [
                ...(playlistsLoading
                    ? [{ label: 'Loading collections…', disabledReason: 'Loading' }]
                    : loadPlaylistsFailed
                      ? [
                            {
                                label: 'Could not load collections. Reopen this menu to retry.',
                                disabledReason: 'Could not load collections',
                            },
                        ]
                      : playlists.results.map((playlist) => ({
                            label: playlist.name || playlist.derived_name || 'Unnamed',
                            to: urls.replayPlaylist(playlist.short_id),
                        }))),
                { label: 'All collections', to: urls.replay(ReplayTabs.Playlists) },
            ],
        },
        { label: 'All recordings', to: urls.replay(ReplayTabs.Home) },
    ]

    useOnMountEffect(() => {
        if (!savedFiltersLoading) {
            loadSavedFilters()
        }
        if (!playlistsLoading && loadPlaylistsFailed) {
            loadPlaylists()
        }
    })

    return <LemonMenuOverlay items={items} />
}
