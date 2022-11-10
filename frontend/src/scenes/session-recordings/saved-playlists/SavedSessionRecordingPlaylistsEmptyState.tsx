import { LemonButton } from 'lib/components/LemonButton'
import { IconPlus } from 'lib/components/icons'
import { useActions } from 'kea'
import { sessionRecordingsLogic } from 'scenes/session-recordings/sessionRecordingsLogic'

export function SavedSessionRecordingPlaylistsEmptyState(): JSX.Element {
    const { saveNewPlaylist } = useActions(sessionRecordingsLogic)

    return (
        <div className="flex items-center justify-center">
            <div className="max-w-lg mt-12 flex flex-col items-center">
                <h2 className="text-xl">There are no playlists that match these filters</h2>
                <p className="text-muted">Once you create a playlist, it will show up here.</p>
                <LemonButton
                    size="large"
                    type="primary"
                    data-attr="add-session-playlist-button-empty-state"
                    icon={<IconPlus />}
                    onClick={() => {
                        saveNewPlaylist({})
                    }}
                >
                    New Playlist
                </LemonButton>
            </div>
        </div>
    )
}
