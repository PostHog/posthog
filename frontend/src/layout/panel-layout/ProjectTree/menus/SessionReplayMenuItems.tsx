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
    const { savedFilters, savedFiltersLoading } = useValues(sessionRecordingSavedFiltersLogic)
    const { loadSavedFiltersIfNeeded } = useActions(sessionRecordingSavedFiltersLogic)
    const { playlists, playlistsLoading } = useValues(sessionRecordingCollectionsLogic)

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
                        loadSavedFiltersIfNeeded()
                    }
                }}
            >
                <MenuSubTrigger asChild>
                    <ButtonPrimitive menuItem>
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
                        ) : null}
                        {!savedFiltersLoading &&
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
                        {!savedFiltersLoading && savedFilters.next ? (
                            <>
                                <MenuSeparator />
                                <MenuItem asChild key="all-saved-filters">
                                    <Link
                                        buttonProps={{
                                            menuItem: true,
                                        }}
                                        to={`${urls.replay(ReplayTabs.Home)}?showFilters=true&filtersTab=saved`}
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

            {playlistsLoading ? (
                <MenuItem disabled>
                    <ButtonPrimitive menuItem>Loading...</ButtonPrimitive>
                </MenuItem>
            ) : playlists.count > 0 ? (
                <MenuSub>
                    <MenuSubTrigger asChild>
                        <ButtonPrimitive menuItem>
                            Collections
                            <IconChevronRight className="ml-auto size-3" />
                        </ButtonPrimitive>
                    </MenuSubTrigger>

                    <MenuSubContent>
                        <MenuGroup>
                            {playlists.results.map((playlist) => (
                                <MenuItem asChild key={playlist.short_id}>
                                    <Link
                                        buttonProps={{
                                            menuItem: true,
                                        }}
                                        to={urls.replayPlaylist(playlist.short_id)}
                                        tooltip={playlist.name || playlist.derived_name || 'Unnamed'}
                                        tooltipPlacement="right"
                                        onKeyDown={handleKeyDown}
                                        onClick={() => onLinkClick?.(false)}
                                    >
                                        <span className="truncate">
                                            {playlist.name || playlist.derived_name || 'Unnamed'}
                                        </span>
                                    </Link>
                                </MenuItem>
                            ))}
                            {playlists.next ? (
                                <>
                                    <DropdownMenuSeparator />
                                    <MenuItem asChild key="all-collections">
                                        <Link
                                            buttonProps={{
                                                menuItem: true,
                                            }}
                                            to={`${urls.replay(ReplayTabs.Playlists)}`}
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
            ) : null}

            <MenuItem asChild>
                <Link
                    buttonProps={{
                        menuItem: true,
                    }}
                    to={urls.replay(ReplayTabs.Home)}
                    onKeyDown={handleKeyDown}
                    onClick={() => onLinkClick?.(false)}
                >
                    All recordings
                </Link>
            </MenuItem>
        </>
    )
}
