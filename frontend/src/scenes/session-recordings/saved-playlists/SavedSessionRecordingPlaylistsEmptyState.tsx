import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconPlus } from 'lib/lemon-ui/icons'
import { createPlaylist } from '../playlist/playlistUtils'
import { useActions, useValues } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { savedSessionRecordingPlaylistsLogic } from './savedSessionRecordingPlaylistsLogic'
import { AvailableFeature, SessionRecordingsTabs } from '~/types'

export function SavedSessionRecordingPlaylistsEmptyState(): JSX.Element {
    const { guardAvailableFeature } = useActions(sceneLogic)
    const playlistsLogic = savedSessionRecordingPlaylistsLogic({ tab: SessionRecordingsTabs.Recent })
    const { playlists } = useValues(playlistsLogic)
    return (
        <div className="flex items-center justify-center">
            <div className="max-w-lg mt-12 flex flex-col items-center">
                <h2 className="text-xl">There are no playlists that match these filters</h2>
                <p className="text-muted">Once you create a playlist, it will show up here.</p>
                <LemonButton
                    type="primary"
                    data-attr="add-session-playlist-button-empty-state"
                    icon={<IconPlus />}
                    onClick={() =>
                        guardAvailableFeature(
                            AvailableFeature.RECORDINGS_PLAYLISTS,
                            'recording playlists',
                            "Playlists allow you to save certain session recordings as a group to easily find and watch them again in the future. You've unfortunately run out of playlists on your current subscription plan.",
                            () => createPlaylist({}, true),
                            undefined,
                            playlists.count
                        )
                    }
                >
                    New playlist
                </LemonButton>
            </div>
        </div>
    )
}
