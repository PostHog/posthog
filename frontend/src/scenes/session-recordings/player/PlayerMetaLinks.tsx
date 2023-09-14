import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerMode,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useActions, useValues } from 'kea'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { IconComment, IconDelete, IconJournalPlus, IconLink } from 'lib/lemon-ui/icons'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'
import { PlaylistPopoverButton } from './playlist-popover/PlaylistPopover'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { NotebookNodeType } from '~/types'
import { useNotebookNode } from 'scenes/notebooks/Nodes/notebookNodeLogic'

export function PlayerMetaLinks(): JSX.Element {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { setPause, deleteRecording } = useActions(sessionRecordingPlayerLogic)
    const nodeLogic = useNotebookNode()

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
                    <NotebookSelectButton
                        size="small"
                        icon={<IconComment />}
                        resource={{ type: NotebookNodeType.Recording, attrs: { id: sessionRecordingId } }}
                        onClick={() => setPause()}
                        onNotebookOpened={(theNotebookLogic, theNodeLogic) => {
                            const time = getCurrentPlayerTime() * 1000

                            if (theNodeLogic) {
                                // Node already exists, we just add a comment
                                theNodeLogic.actions.insertReplayCommentByTimestamp(time, sessionRecordingId)
                                return
                            }

                            theNotebookLogic.actions.insertReplayCommentByTimestamp(time, sessionRecordingId)
                        }}
                    >
                        Comment
                    </NotebookSelectButton>

                    <LemonButton icon={<IconLink />} onClick={onShare} {...commonProps}>
                        <span>Share</span>
                    </LemonButton>

                    {nodeLogic ? (
                        nodeLogic.props.nodeType !== NotebookNodeType.Recording ? (
                            <LemonButton
                                icon={<IconJournalPlus />}
                                size="small"
                                onClick={() => {
                                    nodeLogic.actions.insertAfter({
                                        type: NotebookNodeType.Recording,
                                        attrs: { id: sessionRecordingId },
                                    })
                                }}
                            />
                        ) : null
                    ) : (
                        <PlaylistPopoverButton {...commonProps}>
                            <span>Pin</span>
                        </PlaylistPopoverButton>
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
                </>
            ) : null}
        </div>
    )
}
