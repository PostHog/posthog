import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerMode,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useActions, useValues } from 'kea'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { IconComment, IconDelete, IconLink } from 'lib/lemon-ui/icons'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'
import { PlaylistPopoverButton } from './playlist-popover/PlaylistPopover'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { NotebookAddButton } from 'scenes/notebooks/NotebookAddButton/NotebookAddButton'
import { NotebookNodeType } from '~/types'

export function PlayerMetaLinks(): JSX.Element {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { setPause, deleteRecording } = useActions(sessionRecordingPlayerLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const getCurrentPlayerTime = (): number => {
        // NOTE: We pull this value at call time as otherwise it would trigger re-renders if pulled from the hook
        const playerTime = sessionRecordingPlayerLogic.findMounted(logicProps)?.values.currentPlayerTime || 0
        return Math.floor(playerTime / 1000)
    }

    const onShare = (): void => {
        setPause()
        openPlayerShareDialog({
            seconds: getCurrentPlayerTime(),
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

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard

    return (
        <div className="flex flex-row gap-1 items-center justify-end">
            {![SessionRecordingPlayerMode.Sharing].includes(mode) ? (
                <>
                    {featureFlags[FEATURE_FLAGS.NOTEBOOKS] && (
                        <>
                            <NotebookAddButton
                                size="small"
                                icon={<IconComment />}
                                resource={{ type: NotebookNodeType.Recording, attrs: { id: sessionRecordingId } }}
                                onClick={() => setPause()}
                                onNotebookOpened={(theNotebookLogic, theNodeLogic) => {
                                    const time = getCurrentPlayerTime()

                                    if (theNodeLogic) {
                                        // Node already exists, we just add a comment
                                        theNodeLogic.actions.insertReplayCommentByTimestamp(time, sessionRecordingId)
                                        return
                                    }

                                    theNotebookLogic.actions.insertReplayCommentByTimestamp(time, sessionRecordingId)
                                }}
                            >
                                Comment
                            </NotebookAddButton>
                        </>
                    )}

                    <LemonButton icon={<IconLink />} onClick={onShare} {...commonProps}>
                        <span>Share</span>
                    </LemonButton>

                    <PlaylistPopoverButton {...commonProps}>
                        <span>Pin</span>
                    </PlaylistPopoverButton>

                    {logicProps.playerKey !== 'modal' && (
                        <LemonButton
                            tooltip="Delete"
                            icon={<IconDelete />}
                            onClick={onDelete}
                            {...commonProps}
                            status="danger"
                        />
                    )}
                </>
            ) : null}
        </div>
    )
}
