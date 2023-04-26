import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconDelete, IconLink } from 'lib/lemon-ui/icons'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'
import { PlaylistPopover } from './playlist-popover/PlaylistPopover'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { AddToNotebook } from 'scenes/notebooks/AddToNotebook/AddToNotebook'
import { NotebookNodeType } from 'scenes/notebooks/Nodes/types'

export function PlayerMetaLinks(): JSX.Element {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { setPause, deleteRecording } = useActions(sessionRecordingPlayerLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const onShare = (): void => {
        setPause()
        openPlayerShareDialog({
            seconds: Math.floor((sessionRecordingPlayerLogic.values.currentPlayerTime || 0) / 1000),
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
                onClick: deleteRecording,
            },
        })
    }

    return (
        <div className="flex flex-row gap-1 items-center">
            <LemonButton icon={<IconLink />} onClick={onShare} tooltip="Share recording" size="small">
                Share
            </LemonButton>

            <PlaylistPopover />

            {featureFlags[FEATURE_FLAGS.NOTEBOOKS] && (
                <AddToNotebook node={NotebookNodeType.Recording} properties={{ sessionRecordingId }} />
            )}

            {logicProps.playerKey !== 'modal' && (
                <LemonButton status="danger" onClick={onDelete} size="small">
                    <IconDelete className="text-lg" />
                </LemonButton>
            )}
        </div>
    )
}
