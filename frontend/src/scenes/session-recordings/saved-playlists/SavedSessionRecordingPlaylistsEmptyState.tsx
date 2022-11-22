import { LemonButton } from 'lib/components/LemonButton'
import { IconPlus } from 'lib/components/icons'
import { useActions, useValues } from 'kea'
import { SessionRecordingsTabs } from '~/types'
import { savedSessionRecordingPlaylistsLogic } from './savedSessionRecordingPlaylistsLogic'

export function SavedSessionRecordingPlaylistsEmptyState({ tab }: { tab: SessionRecordingsTabs }): JSX.Element {
    const { newPlaylistLoading } = useValues(savedSessionRecordingPlaylistsLogic({ tab }))
    const { createSavedPlaylist } = useActions(savedSessionRecordingPlaylistsLogic({ tab }))

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
                    loading={newPlaylistLoading}
                    onClick={() => {
                        createSavedPlaylist({}, true)
                    }}
                >
                    New Playlist
                </LemonButton>
            </div>
        </div>
    )
}
