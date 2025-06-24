import { IconPinFilled } from '@posthog/icons'
import { useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { savedSessionRecordingPlaylistsLogic } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistsLogic'
import { urls } from 'scenes/urls'

import { ReplayTabs } from '~/types'

import { CustomMenuProps } from '../types'

export function SessionReplayMenuItems({ MenuItem = DropdownMenuItem, onLinkClick }: CustomMenuProps): JSX.Element {
    const { playlists, playlistsLoading } = useValues(
        savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Playlists })
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
            {playlists.count > 0 ? (
                playlists.results.map((playlist) => (
                    <MenuItem asChild key={playlist.short_id}>
                        <Link
                            buttonProps={{
                                menuItem: true,
                            }}
                            to={urls.replayPlaylist(playlist.short_id)}
                            onKeyDown={handleKeyDown}
                            onClick={() => onLinkClick?.(false)}
                        >
                            <IconPinFilled className="size-3 text-tertiary" />
                            <span className="truncate">{playlist.name || playlist.derived_name || 'Unnamed'}</span>
                        </Link>
                    </MenuItem>
                ))
            ) : playlistsLoading ? (
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
                            Playlists
                        </Link>
                    </MenuItem>
                </>
            )}
        </>
    )
}
