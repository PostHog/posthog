import { IconPinFilled } from '@posthog/icons'
import { useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { savedSessionRecordingPlaylistsLogic } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistsLogic'
import { urls } from 'scenes/urls'

import { ReplayTabs } from '~/types'

import { panelLayoutLogic } from '../../panelLayoutLogic'
import { CustomMenuProps } from '../types'

export function SessionReplayMenu({ MenuItem, MenuSeparator }: CustomMenuProps): JSX.Element {
    const { playlists, playlistsLoading } = useValues(
        savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Playlists })
    )
    const { mainContentRef } = useValues(panelLayoutLogic)

    function handleKeyDown(e: React.KeyboardEvent<HTMLElement>): void {
        if (e.key === 'Enter' || e.key === ' ') {
            // small delay to fight dropdown menu from taking focus
            setTimeout(() => {
                mainContentRef?.current?.focus()
            }, 10)
        }
    }
    return (
        <>
            {playlists.count > 0 ? (
                playlists.results.map((playlist) => (
                    <MenuItem key={playlist.id} asChild>
                        <Link
                            buttonProps={{
                                menuItem: true,
                            }}
                            to={urls.replayPlaylist(playlist.short_id)}
                            onKeyDown={handleKeyDown}
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
                        >
                            Playlists
                        </Link>
                    </MenuItem>
                </>
            )}
            <MenuSeparator />
        </>
    )
}
