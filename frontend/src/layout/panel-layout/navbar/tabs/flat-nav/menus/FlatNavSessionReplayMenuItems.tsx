import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import {
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    Skeleton,
} from '@posthog/quill'

import { sessionRecordingCollectionsLogic } from 'scenes/session-recordings/collections/sessionRecordingCollectionsLogic'
import { sessionRecordingSavedFiltersLogic } from 'scenes/session-recordings/filters/sessionRecordingSavedFiltersLogic'
import { urls } from 'scenes/urls'

import { ReplayTabs } from '~/types'

import { FlatNavMenuLinkItem } from './FlatNavMenuLinkItem'

// An absolute URL makes the link reload the page. sessionRecordingSavedFiltersLogic reads
// savedFilterId in afterMount only, so a client-side push leaves the filter unapplied whenever
// Replay home already holds that logic mounted.
function savedFilterUrl(savedFilterId: string): string {
    return urls.absolute(combineUrl(urls.replay(ReplayTabs.Home), { savedFilterId }).url)
}

export function FlatNavSessionReplayMenuItems(): JSX.Element {
    const { savedFilters, savedFiltersLoading, loadSavedFiltersFailed } = useValues(sessionRecordingSavedFiltersLogic)
    const { loadSavedFilters, loadSavedFiltersIfNeeded } = useActions(sessionRecordingSavedFiltersLogic)
    const { playlists, playlistsLoading, loadPlaylistsFailed } = useValues(sessionRecordingCollectionsLogic)
    const { loadPlaylists } = useActions(sessionRecordingCollectionsLogic)

    return (
        <>
            <DropdownMenuSub
                onOpenChange={(open) => {
                    if (!open || savedFiltersLoading) {
                        return
                    }
                    // loadSavedFiltersIfNeeded refuses to load again once one load has succeeded,
                    // so a later failure needs the load forced or the submenu never recovers
                    if (loadSavedFiltersFailed) {
                        loadSavedFilters()
                    } else {
                        loadSavedFiltersIfNeeded()
                    }
                }}
            >
                <DropdownMenuSubTrigger>Saved filters</DropdownMenuSubTrigger>
                <DropdownMenuSubContent data-lemon-skin className="min-w-48">
                    {savedFiltersLoading ? (
                        <Skeleton className="mx-2 my-1 h-4 w-32" />
                    ) : savedFilters.results.length === 0 ? (
                        loadSavedFiltersFailed ? (
                            <DropdownMenuItem disabled>Couldn't load saved filters</DropdownMenuItem>
                        ) : (
                            <DropdownMenuItem disabled>No saved filters</DropdownMenuItem>
                        )
                    ) : (
                        savedFilters.results.map((savedFilter) => (
                            <FlatNavMenuLinkItem key={savedFilter.short_id} to={savedFilterUrl(savedFilter.short_id)}>
                                {savedFilter.name || savedFilter.derived_name || 'Unnamed'}
                            </FlatNavMenuLinkItem>
                        ))
                    )}
                    {!savedFiltersLoading && savedFilters.next && (
                        <>
                            <DropdownMenuSeparator />
                            <FlatNavMenuLinkItem
                                to={`${urls.replay(ReplayTabs.Home)}?showFilters=true&filtersTab=saved`}
                            >
                                All saved filters
                            </FlatNavMenuLinkItem>
                        </>
                    )}
                </DropdownMenuSubContent>
            </DropdownMenuSub>

            {playlistsLoading || loadPlaylistsFailed || playlists.count > 0 ? (
                <DropdownMenuSub
                    onOpenChange={(open) => {
                        if (open && loadPlaylistsFailed && !playlistsLoading) {
                            loadPlaylists()
                        }
                    }}
                >
                    <DropdownMenuSubTrigger>Collections</DropdownMenuSubTrigger>
                    <DropdownMenuSubContent data-lemon-skin className="min-w-48">
                        {playlistsLoading ? (
                            <Skeleton className="mx-2 my-1 h-4 w-32" />
                        ) : playlists.results.length === 0 ? (
                            loadPlaylistsFailed ? (
                                <DropdownMenuItem disabled>Couldn't load collections</DropdownMenuItem>
                            ) : (
                                <DropdownMenuItem disabled>No collections</DropdownMenuItem>
                            )
                        ) : (
                            playlists.results.map((playlist) => (
                                <FlatNavMenuLinkItem
                                    key={playlist.short_id}
                                    to={urls.replayPlaylist(playlist.short_id)}
                                >
                                    {playlist.name || playlist.derived_name || 'Unnamed'}
                                </FlatNavMenuLinkItem>
                            ))
                        )}
                        {!playlistsLoading && playlists.next && (
                            <>
                                <DropdownMenuSeparator />
                                <FlatNavMenuLinkItem to={urls.replay(ReplayTabs.Playlists)}>
                                    All collections
                                </FlatNavMenuLinkItem>
                            </>
                        )}
                    </DropdownMenuSubContent>
                </DropdownMenuSub>
            ) : null}

            <FlatNavMenuLinkItem to={urls.replay(ReplayTabs.Home)}>All recordings</FlatNavMenuLinkItem>
        </>
    )
}
