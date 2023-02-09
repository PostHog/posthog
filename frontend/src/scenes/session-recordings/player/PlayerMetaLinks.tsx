import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useActions } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconDelete, IconLink } from 'lib/lemon-ui/icons'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'
import { PlaylistPopover } from './playlist-popover/PlaylistPopover'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

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

    const onDelete = (): void => {
        LemonDialog.open({
            title: 'Delete recording',
            description: 'Are you sure you want to delete this recording? This cannot be undone.',
            secondaryButton: {
                children: 'Cancel',
            },
            primaryButton: {
                children: 'Delete',
                status: 'danger',
            },
        })
    }

    return (
        <div className="flex flex-row gap-2">
            <LemonButton icon={<IconLink />} onClick={onShare} tooltip="Share recording" size="small">
                Share
            </LemonButton>

            <PlaylistPopover {...props} />

            <LemonButton status="danger" icon={<IconDelete />} onClick={onDelete} />
        </div>
    )
}
