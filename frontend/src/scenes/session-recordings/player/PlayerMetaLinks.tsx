import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { openPlayerAddToPlaylistDialog } from 'scenes/session-recordings/player/add-to-playlist/PlayerAddToPlaylist'
import { IconLink, IconPlus, IconWithCount } from 'lib/components/icons'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'
import { playerSettingsLogic } from './playerSettingsLogic'

export function PlayerMetaLinks({ sessionRecordingId, playerKey }: SessionRecordingPlayerLogicProps): JSX.Element {
    const logic = sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    const { recordingStartTime, sessionPlayerData } = useValues(logic)
    const { setPause } = useActions(logic)
    const playlists = sessionPlayerData.metadata.playlists ?? []
    const { isFullScreen } = useValues(playerSettingsLogic)

    const onShare = (): void => {
        setPause()
        openPlayerShareDialog({
            seconds: Math.floor((logic.values.currentPlayerTime || 0) / 1000),
            id: sessionRecordingId,
        })
    }

    const onAddToPlaylist = (): void => {
        setPause()
        openPlayerAddToPlaylistDialog({
            sessionRecordingId,
            playerKey,
            recordingStartTime,
        })
    }

    return (
        <div className="flex flex-row gap-2">
            <LemonButton icon={<IconLink />} onClick={onShare} tooltip="Share recording" size={'small'}>
                Share
            </LemonButton>
            <LemonButton
                onClick={onAddToPlaylist}
                icon={
                    <IconWithCount count={playlists.length}>
                        <IconPlus />
                    </IconWithCount>
                }
                size={'small'}
                tooltip="Save recording to static playlist"
            >
                Save
            </LemonButton>
        </div>
    )
}
