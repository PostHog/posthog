import { useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconChevronRight } from '@posthog/icons'

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
    MenuSeparator = DropdownMenuSeparator,
    MenuGroup = DropdownMenuGroup,
    onLinkClick,
}: CustomMenuProps): JSX.Element {
    const { savedFilters, savedFiltersLoading } = useValues(sessionRecordingSavedFiltersLogic)
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
            {savedFiltersLoading ? (
                <MenuItem disabled>
                    <ButtonPrimitive menuItem>Loading...</ButtonPrimitive>
                </MenuItem>
            ) : savedFilters.count > 0 ? (
                <MenuSub>
                    <MenuSubTrigger asChild>
                        <ButtonPrimitive menuItem>
                            Saved filters
                            <IconChevronRight className="ml-auto size-3" />
                        </ButtonPrimitive>
                    </MenuSubTrigger>

                    <MenuSubContent>
                        <MenuGroup>
                            {savedFilters.results.map((savedFilter) => (
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
                                        onKeyDown={handleKeyDown}
                                        onClick={() => onLinkClick?.(false)}
                                    >
                                        <span className="truncate">
                                            {savedFilter.name || savedFilter.derived_name || 'Unnamed'}
                                        </span>
                                    </Link>
                                </MenuItem>
                            ))}
                            {savedFilters.next ? (
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
            ) : null}

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
