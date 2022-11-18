import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { openPlayerAddToPlaylistDialog } from 'scenes/session-recordings/player/add-to-playlist/PlayerAddToPlaylist'
import { IconLink, IconSave } from 'lib/components/icons'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'

export function PlayerHeader({ sessionRecordingId, playerKey }: SessionRecordingPlayerLogicProps): JSX.Element {
    const logic = sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    const { recordingStartTime, sessionPlayerData } = useValues(logic)
    const { setPause } = useActions(logic)

    const onShare = (): void => {
        setPause()
        openPlayerShareDialog({
            seconds: Math.floor((logic.values.currentPlayerTime || 0) / 1000),
            id: sessionRecordingId,
        })
    }

    console.log('ADDRECORDINGTO', sessionPlayerData)

    const onAddToPlaylist = (): void => {
        setPause()
        openPlayerAddToPlaylistDialog({
            recording: {
                id: sessionRecordingId,
                playlists: sessionPlayerData.metadata.playlists,
                start_time: recordingStartTime,
            },
        })
    }

    return (
        <div className="py-2 px-3 flex flex-row justify-end gap-3">
            <LemonButton icon={<IconLink />} status="primary-alt" onClick={() => onShare()} tooltip="Share recording">
                Share
            </LemonButton>
            <LemonButton
                status="primary-alt"
                onClick={onAddToPlaylist}
                icon={<IconSave />}
                tooltip="Save recording to static playlist"
            >
                Save
            </LemonButton>
        </div>
    )
}
