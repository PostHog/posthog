import {
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { useActions, useValues } from 'kea'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { IconDelete, IconLink } from 'lib/lemon-ui/icons'
import { openPlayerShareDialog } from 'scenes/session-recordings/player/share/PlayerShare'
import { PlaylistPopoverButton } from './playlist-popover/PlaylistPopover'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { NotebookNodeType } from '~/types'

export function PlayerMetaLinks(): JSX.Element {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { setPause, deleteRecording } = useActions(sessionRecordingPlayerLogic)

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

    const onComment = (): void => {
        const logic = notebookLogic.findMounted({ shortId: logicProps.notebookShortId })
        const currentPlayerTime = sessionRecordingPlayerLogic.findMounted(logicProps)?.values.currentPlayerTime || 0

        logic?.values.editor?.insertNodeAfter('ph-recording', [
            {
                type: 'paragraph',
                content: [
                    {
                        type: NotebookNodeType.Timestamp,
                        attrs: { playbackTime: currentPlayerTime, sessionRecordingId: sessionRecordingId },
                    },
                    { type: 'text', text: ' ' },
                ],
            },
        ])
    }

    const commonProps: Partial<LemonButtonProps> = {
        size: 'small',
    }

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard

    const isInNotebook = notebookLogic.isMounted({ shortId: logicProps.notebookShortId })

    console.log(isInNotebook)

    return (
        <div className="flex flex-row gap-1 items-center justify-end">
            {![SessionRecordingPlayerMode.Notebook, SessionRecordingPlayerMode.Sharing].includes(mode) ? (
                <>
                    {isInNotebook && (
                        <LemonButton icon={<IconLink />} onClick={onComment} {...commonProps}>
                            <span>Comment</span>
                        </LemonButton>
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
