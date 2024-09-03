import { IconPlus } from '@posthog/icons'
import { useValues } from 'kea'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { AvailableFeature, ReplayTabs } from '~/types'

import { createPlaylist } from '../playlist/playlistUtils'
import { savedSessionRecordingPlaylistsLogic } from './savedSessionRecordingPlaylistsLogic'

export function SavedSessionRecordingPlaylistsEmptyState(): JSX.Element {
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const playlistsLogic = savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Home })
    const { playlists, loadPlaylistsFailed } = useValues(playlistsLogic)
    return loadPlaylistsFailed ? (
        <LemonBanner type="error">Error while trying to load playlist.</LemonBanner>
    ) : (
        <div className="flex items-center justify-center">
            <div className="max-w-248 mt-12 flex flex-col items-center">
                <h2 className="text-xl">There are no playlists that match these filters</h2>
                <p className="text-muted">Once you create a playlist, it will show up here.</p>
                <LemonButton
                    type="primary"
                    data-attr="add-session-playlist-button-empty-state"
                    icon={<IconPlus />}
                    onClick={() =>
                        guardAvailableFeature(
                            AvailableFeature.RECORDINGS_PLAYLISTS,
                            () => void createPlaylist({}, true),
                            { currentUsage: playlists.count }
                        )
                    }
                >
                    New playlist
                </LemonButton>
            </div>
        </div>
    )
}
