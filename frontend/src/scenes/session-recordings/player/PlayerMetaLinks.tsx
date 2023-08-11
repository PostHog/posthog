import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerMode,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useActions, useValues } from 'kea'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { IconDelete, IconLink } from 'lib/lemon-ui/icons'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'
import { PlaylistPopoverButton } from './playlist-popover/PlaylistPopover'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { buildTimestampCommentContent } from 'scenes/notebooks/Nodes/NotebookNodeReplayTimestamp'
import { useNotebookNode } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import { NotebookNodeType, NotebookTarget } from '~/types'
import { notebooksListLogic, openNotebook } from 'scenes/notebooks/Notebook/notebooksListLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dayjs } from 'lib/dayjs'
import { NotebookCommentButton } from 'scenes/notebooks/NotebookCommentButton/NotebookCommentButton'
import { useCallback } from 'react'

export function PlayerMetaLinks(): JSX.Element {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { setPause, deleteRecording } = useActions(sessionRecordingPlayerLogic)
    const { createNotebook } = useActions(notebooksListLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const nodeLogic = useNotebookNode()

    const getCurrentPlayerTime = (): number => {
        // NOTE: We pull this value at call time as otherwise it would trigger re-renders if pulled from the hook
        const playerTime = sessionRecordingPlayerLogic.findMounted(logicProps)?.values.currentPlayerTime || 0
        return Math.floor(playerTime / 1000)
    }

    const commentInExistingNotebook = useCallback(
        async (notebookShortId) => {
            const currentPlayerTime = getCurrentPlayerTime() * 1000
            await openNotebook(notebookShortId, NotebookTarget.Popover, null, (theNotebookLogic) => {
                const ed = theNotebookLogic.values.editor
                if (ed === null) {
                    // this should never happen, `openNotebook` waits until the logic's editor is not null
                    return
                }
                const recordingPosition = ed.findNodePositionByAttrs({ id: sessionRecordingId })
                theNotebookLogic.actions.insertAfterLastNodeOfType(
                    NotebookNodeType.ReplayTimestamp,
                    [buildTimestampCommentContent(currentPlayerTime, sessionRecordingId)],
                    recordingPosition
                )
            })
        },
        [nodeLogic]
    )

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
                            <NotebookCommentButton
                                sessionRecordingId={sessionRecordingId}
                                onCommentInNewNotebook={() => {
                                    const title = `Session Replay Notes ${dayjs().format('DD/MM')}`
                                    const currentPlayerTime = getCurrentPlayerTime() * 1000
                                    createNotebook(title, NotebookTarget.Popover, [
                                        {
                                            type: NotebookNodeType.Recording,
                                            attrs: { id: sessionRecordingId },
                                        },
                                        buildTimestampCommentContent(currentPlayerTime, sessionRecordingId),
                                    ])
                                }}
                                onCommentInExistingNotebook={commentInExistingNotebook}
                            />
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
