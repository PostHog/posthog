import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useActions } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconLink } from 'lib/lemon-ui/icons'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'
import { PlaylistPopup } from './playlist-popup/PlaylistPopup'

export function PlayerMetaLinks(props: SessionRecordingPlayerLogicProps): JSX.Element {
    const { sessionRecordingId } = props
    const logic = sessionRecordingPlayerLogic(props)
    const { setPause } = useActions(logic)

    const onShare = (): void => {
        setPause()
        openPlayerShareDialog({
            seconds: Math.floor((logic.values.currentPlayerTime || 0) / 1000),
            id: sessionRecordingId,
        })
    }

    return (
        <div className="flex flex-row gap-2">
            <LemonButton icon={<IconLink />} onClick={onShare} tooltip="Share recording" size="small">
                Share
            </LemonButton>

            <PlaylistPopup {...props} />
        </div>
    )
}
