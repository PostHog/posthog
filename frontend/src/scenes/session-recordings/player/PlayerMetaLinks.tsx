import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerMode,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useActions, useValues } from 'kea'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { IconComment, IconDelete, IconLink, IconPinFilled, IconPinOutline } from 'lib/lemon-ui/icons'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'
import { PlaylistPopoverButton } from './playlist-popover/PlaylistPopover'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { NotebookNodeType } from '~/types'
import { useNotebookNode } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import { sessionPlayerModalLogic } from './modal/sessionPlayerModalLogic'
import { personsModalLogic } from 'scenes/trends/persons-modal/personsModalLogic'
import { IconNotebook } from 'scenes/notebooks/IconNotebook'

export function PlayerMetaLinks(): JSX.Element {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { setPause, deleteRecording, maybePersistRecording } = useActions(sessionRecordingPlayerLogic)
    const nodeLogic = useNotebookNode()
    const { closeSessionPlayer } = useActions(sessionPlayerModalLogic())

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
                        resource={{
                            type: NotebookNodeType.Recording,
                            attrs: { id: sessionRecordingId, __init: { expanded: true } },
                        }}
                        onClick={() => setPause()}
                        onNotebookOpened={(theNotebookLogic, theNodeLogic) => {
                            const time = getCurrentPlayerTime() * 1000

                            if (theNodeLogic) {
                                // Node already exists, we just add a comment
                                theNodeLogic.actions.insertReplayCommentByTimestamp(time, sessionRecordingId)
                                return
                            } else {
                                theNotebookLogic.actions.insertReplayCommentByTimestamp({
                                    timestamp: time,
                                    sessionRecordingId,
                                })
                            }

                            closeSessionPlayer()
                            personsModalLogic.findMounted()?.actions.closeModal()
                        }}
                    >
                        Comment
                    </NotebookSelectButton>

                    <LemonButton icon={<IconLink />} onClick={onShare} {...commonProps}>
                        <span>Share</span>
                    </LemonButton>

                    {nodeLogic?.props.nodeType === NotebookNodeType.RecordingPlaylist ? (
                        <LemonButton
                            icon={<IconNotebook />}
                            size="small"
                            onClick={() => {
                                nodeLogic.actions.insertAfter({
                                    type: NotebookNodeType.Recording,
                                    attrs: { id: sessionRecordingId },
                                })
                            }}
                        />
                    ) : null}

                    {logicProps.setPinned ? (
                        <LemonButton
                            onClick={() => {
                                if (nodeLogic && !logicProps.pinned) {
                                    // If we are in a node, then pinning should persist the recording
                                    maybePersistRecording()
                                }

                                logicProps.setPinned?.(!logicProps.pinned)
                            }}
                            size="small"
                            tooltip={logicProps.pinned ? 'Unpin from this list' : 'Pin to this list'}
                            icon={logicProps.pinned ? <IconPinFilled /> : <IconPinOutline />}
                        />
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
