import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { IconLink } from 'lib/components/icons'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'
import { playerSettingsLogic } from './playerSettingsLogic'
import { PlaylistPopup } from './playlist-popup/PlaylistPopup'

export function PlayerMetaLinks({ sessionRecordingId, playerKey }: SessionRecordingPlayerLogicProps): JSX.Element {
    const logic = sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    const { setPause } = useActions(logic)
    const { isFullScreen } = useValues(playerSettingsLogic)

    const onShare = (): void => {
        setPause()
        openPlayerShareDialog({
            seconds: Math.floor((logic.values.currentPlayerTime || 0) / 1000),
            id: sessionRecordingId,
        })
    }

    return (
        <div className="flex flex-row justify-end gap-2">
            <LemonButton
                icon={<IconLink />}
                onClick={onShare}
                tooltip="Share recording"
                size={isFullScreen ? 'small' : 'medium'}
            >
                Share
            </LemonButton>

            <PlaylistPopup sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
        </div>
    )
}
