import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconChevronRight } from '@posthog/icons'
import { LemonSkeleton } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { sessionRecordingCollectionsLogic } from 'scenes/session-recordings/collections/sessionRecordingCollectionsLogic'
import { sessionRecordingSavedFiltersLogic } from 'scenes/session-recordings/filters/sessionRecordingSavedFiltersLogic'
import { urls } from 'scenes/urls'

import { ReplayTabs } from '~/types'

import { CustomMenuProps } from '../types'

export function SessionReplayMenuItems({
    MenuItem = DropdownMenuItem,
    MenuSub = DropdownMenuSub,
    MenuSubTrigger = DropdownMenuSubTrigger,
    MenuSubContent = DropdownMenuSubContent,
    MenuGroup = DropdownMenuGroup,
    MenuSeparator = DropdownMenuSeparator,
    onLinkClick,
}: CustomMenuProps): JSX.Element {
    const { savedFilters, savedFiltersLoading, loadSavedFiltersFailed } = useValues(sessionRecordingSavedFiltersLogic)
    const { loadSavedFiltersIfNeeded, loadSavedFilters } = useActions(sessionRecordingSavedFiltersLogic)
    const { playlists, playlistsLoading, loadPlaylistsFailed } = useValues(sessionRecordingCollectionsLogic)
    const { loadPlaylists } = useActions(sessionRecordingCollectionsLogic)

    function handleKeyDown(e: React.KeyboardEvent<HTMLElement>): void {
        if (e.key === 'Enter' || e.key === ' ') {
            // small delay to fight dropdown menu from taking focus
            setTimeout(() => {
                onLinkClick?.(true)
            }, 10)
        }
    }
    return (
        <>
            <MenuSub
                onOpenChange={(open) => {
                    if (open) {
                        if (loadSavedFiltersFailed) {
                            loadSavedFilters()
                        } else {
                            loadSavedFiltersIfNeeded()
                        }
                    }
                }}
            >
                <MenuSubTrigger asChild>
                    <ButtonPrimitive menuItem data-attr="tree-item-menu-saved-filters">
                        Saved filters
                        <IconChevronRight className="ml-auto size-3" />
                    </ButtonPrimitive>
                </MenuSubTrigger>

                <MenuSubContent>
                    <MenuGroup>
                        {savedFiltersLoading ? (
                            <MenuItem disabled>
                                <LemonSkeleton className="h-4 w-32" repeat={3} />
                            </MenuItem>
                        ) : loadSavedFiltersFailed ? (
                            <MenuItem disabled>
                                <ButtonPrimitive menuItem>Couldn't load saved filters</ButtonPrimitive>
                            </MenuItem>
                        ) : null}
                        {!savedFiltersLoading &&
                            !loadSavedFiltersFailed &&
                            savedFilters.results.map((savedFilter) => (
                                <MenuItem asChild key={savedFilter.short_id}>
                                    <Link
                                        buttonProps={{
                                            menuItem: true,
                                        }}
                                        to={urls.absolute(
                                            combineUrl(urls.replay(ReplayTabs.Home), {
                                                savedFilterId: savedFilter.short_id,
                                            }).url
                                        )}
                                        tooltip={savedFilter.name || savedFilter.derived_name || 'Unnamed'}
                                        data-attr="tree-item-menu-saved-filter"
                                        tooltipPlacement="right"
                                        onKeyDown={handleKeyDown}
                                        onClick={() => onLinkClick?.(false)}
                                    >
                                        <span className="truncate">
                                            {savedFilter.name || savedFilter.derived_name || 'Unnamed'}
                                        </span>
                                    </Link>
                                </MenuItem>
                            ))}
                        {!savedFiltersLoading ? (
                            <>
                                {savedFilters.results.length > 0 && !loadSavedFiltersFailed && <MenuSeparator />}
                                <MenuItem asChild key="all-saved-filters">
                                    <Link
                                        buttonProps={{
                                            menuItem: true,
                                        }}
                                        to={`${urls.replay(ReplayTabs.Home)}?showFilters=true&filtersTab=saved`}
                                        data-attr="tree-item-menu-all-saved-filters"
                                        onKeyDown={handleKeyDown}
                                        onClick={() => onLinkClick?.(false)}
                                    >
                                        <span className="truncate">All saved filters</span>
                                    </Link>
                                </MenuItem>
                            </>
                        ) : null}
                    </MenuGroup>
                </MenuSubContent>
            </MenuSub>

            <MenuSub
                onOpenChange={(open) => {
                    if (open && loadPlaylistsFailed && !playlistsLoading) {
                        loadPlaylists()
                    }
                }}
            >
                <MenuSubTrigger asChild>
                    <ButtonPrimitive menuItem data-attr="tree-item-menu-collections">
                        Collections
                        <IconChevronRight className="ml-auto size-3" />
                    </ButtonPrimitive>
                </MenuSubTrigger>

                <MenuSubContent>
                    <MenuGroup>
                        {playlistsLoading ? (
                            <MenuItem disabled>
                                <LemonSkeleton className="h-4 w-32" repeat={3} />
                            </MenuItem>
                        ) : loadPlaylistsFailed ? (
                            <MenuItem disabled>
                                <ButtonPrimitive menuItem>Couldn't load collections</ButtonPrimitive>
                            </MenuItem>
                        ) : (
                            playlists.results.map((playlist) => (
                                <MenuItem asChild key={playlist.short_id}>
                                    <Link
                                        buttonProps={{
                                            menuItem: true,
                                        }}
                                        to={urls.replayPlaylist(playlist.short_id)}
                                        tooltip={playlist.name || playlist.derived_name || 'Unnamed'}
                                        data-attr="tree-item-menu-collection"
                                        tooltipPlacement="right"
                                        onKeyDown={handleKeyDown}
                                        onClick={() => onLinkClick?.(false)}
                                    >
                                        <span className="truncate">
                                            {playlist.name || playlist.derived_name || 'Unnamed'}
                                        </span>
                                    </Link>
                                </MenuItem>
                            ))
                        )}
                        {!playlistsLoading ? (
                            <>
                                {playlists.results.length > 0 && !loadPlaylistsFailed && <MenuSeparator />}
                                <MenuItem asChild key="all-collections">
                                    <Link
                                        buttonProps={{
                                            menuItem: true,
                                        }}
                                        to={urls.replay(ReplayTabs.Playlists)}
                                        data-attr="tree-item-menu-all-collections"
                                        onKeyDown={handleKeyDown}
                                        onClick={() => onLinkClick?.(false)}
                                    >
                                        <span className="truncate">All collections</span>
                                    </Link>
                                </MenuItem>
                            </>
                        ) : null}
                    </MenuGroup>
                </MenuSubContent>
            </MenuSub>

            <MenuItem asChild>
                <Link
                    buttonProps={{
                        menuItem: true,
                    }}
                    to={urls.replay(ReplayTabs.Home)}
                    data-attr="tree-item-menu-all-recordings"
                    onKeyDown={handleKeyDown}
                    onClick={() => onLinkClick?.(false)}
                >
                    All recordings
                </Link>
            </MenuItem>
        </>
    )
}
