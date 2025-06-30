import { useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { savedSessionRecordingPlaylistsLogic } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistsLogic'
import { urls } from 'scenes/urls'

import { ReplayTabs } from '~/types'

import { CustomMenuProps } from '../types'
import { combineUrl } from 'kea-router'

export function SessionReplayMenuItems({ MenuItem = DropdownMenuItem, onLinkClick }: CustomMenuProps): JSX.Element {
    const { savedFilters, savedFiltersLoading } = useValues(
        savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Home })
    )

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
            {savedFilters.count > 0 ? (
                savedFilters.results.map((savedFilter) => (
                    <MenuItem asChild key={savedFilter.short_id}>
                        <Link
                            buttonProps={{
                                menuItem: true,
                            }}
                            to={urls.absolute(
                                combineUrl(urls.replay(ReplayTabs.Home), { savedFilterId: savedFilter.short_id }).url
                            )}
                            onKeyDown={handleKeyDown}
                            onClick={() => onLinkClick?.(false)}
                        >
                            <span className="truncate">
                                {savedFilter.name || savedFilter.derived_name || 'Unnamed'}
                            </span>
                        </Link>
                    </MenuItem>
                ))
            ) : savedFiltersLoading ? (
                <MenuItem disabled>
                    <ButtonPrimitive menuItem>Loading...</ButtonPrimitive>
                </MenuItem>
            ) : (
                <>
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

                    <MenuItem asChild>
                        <Link
                            buttonProps={{
                                menuItem: true,
                            }}
                            to={urls.replay(ReplayTabs.Playlists)}
                            onKeyDown={handleKeyDown}
                            onClick={() => onLinkClick?.(false)}
                        >
                            Collections
                        </Link>
                    </MenuItem>
                </>
            )}
        </>
    )
}
