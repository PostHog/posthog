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

export function FlatNavSessionReplayMenuItems(): JSX.Element {
    const { savedFilters, savedFiltersLoading } = useValues(sessionRecordingSavedFiltersLogic)
    const { loadSavedFiltersIfNeeded } = useActions(sessionRecordingSavedFiltersLogic)
    const { playlists, playlistsLoading } = useValues(sessionRecordingCollectionsLogic)

    return (
        <>
            <DropdownMenuSub
                onOpenChange={(open) => {
                    if (open) {
                        loadSavedFiltersIfNeeded()
                    }
                }}
            >
                <DropdownMenuSubTrigger>Saved filters</DropdownMenuSubTrigger>
                <DropdownMenuSubContent data-lemon-skin className="min-w-48">
                    {savedFiltersLoading ? (
                        <Skeleton className="mx-2 my-1 h-4 w-32" />
                    ) : savedFilters.results.length === 0 ? (
                        <DropdownMenuItem disabled>No saved filters</DropdownMenuItem>
                    ) : (
                        savedFilters.results.map((savedFilter) => (
                            <FlatNavMenuLinkItem
                                key={savedFilter.short_id}
                                to={
                                    combineUrl(urls.replay(ReplayTabs.Home), { savedFilterId: savedFilter.short_id })
                                        .url
                                }
                            >
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

            {playlistsLoading || playlists.count > 0 ? (
                <DropdownMenuSub>
                    <DropdownMenuSubTrigger>Collections</DropdownMenuSubTrigger>
                    <DropdownMenuSubContent data-lemon-skin className="min-w-48">
                        {playlistsLoading ? (
                            <Skeleton className="mx-2 my-1 h-4 w-32" />
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
