import { LemonButton } from 'lib/components/LemonButton'
import { IconPlus } from 'lib/components/icons'
import { createPlaylist } from '../playlist/playlistUtils'

export function SavedSessionRecordingPlaylistsEmptyState(): JSX.Element {
    return (
        <div className="flex items-center justify-center">
            <div className="max-w-lg mt-12 flex flex-col items-center">
                <h2 className="text-xl">There are no playlists that match these filters</h2>
                <p className="text-muted">Once you create a playlist, it will show up here.</p>
                <LemonButton
                    type="primary"
                    data-attr="add-session-playlist-button-empty-state"
                    icon={<IconPlus />}
                    onClick={() => createPlaylist({}, true)}
                >
                    New playlist
                </LemonButton>
            </div>
        </div>
    )
}
