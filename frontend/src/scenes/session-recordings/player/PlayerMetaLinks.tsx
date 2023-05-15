import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useActions, useValues } from 'kea'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { IconDelete, IconLink } from 'lib/lemon-ui/icons'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'
import { PlaylistPopoverButton } from './playlist-popover/PlaylistPopover'
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
        // NOTE: We pull this value at call time as otherwise it would trigger rerenders if pulled from the hook
        const currentPlayerTime = sessionRecordingPlayerLogic.findMounted(logicProps)?.values.currentPlayerTime || 0
        openPlayerShareDialog({
            seconds: Math.floor(currentPlayerTime / 1000),
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

    const commonProps: Partial<LemonButtonProps> = {
        size: 'small',
    }

    return (
        <div className="flex flex-row gap-1 items-center justify-end">
            <LemonButton icon={<IconLink />} onClick={onShare} {...commonProps}>
                <span>Share</span>
            </LemonButton>

            <PlaylistPopoverButton {...commonProps}>
                <span>Pin</span>
            </PlaylistPopoverButton>

            {featureFlags[FEATURE_FLAGS.NOTEBOOKS] && (
                <AddToNotebook
                    tooltip="Add to Notebook"
                    node={NotebookNodeType.Recording}
                    properties={{ id: sessionRecordingId }}
                    {...commonProps}
                />
            )}

            {logicProps.playerKey !== 'modal' && (
                <LemonButton
                    tooltip="Delete"
                    icon={<IconDelete />}
                    onClick={onDelete}
                    {...commonProps}
                    status="danger"
                />
            )}
        </div>
    )
}
