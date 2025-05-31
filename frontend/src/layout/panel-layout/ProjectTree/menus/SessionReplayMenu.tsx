import { IconPinFilled } from '@posthog/icons'
import { useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { savedSessionRecordingPlaylistsLogic } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistsLogic'
import { urls } from 'scenes/urls'

import { ReplayTabs } from '~/types'

import { CustomMenuProps } from '../types'

export function SessionReplayMenu({ MenuItem, MenuSeparator }: CustomMenuProps): JSX.Element {
    const { playlists, playlistsLoading } = useValues(
        savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Playlists })
    )

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
