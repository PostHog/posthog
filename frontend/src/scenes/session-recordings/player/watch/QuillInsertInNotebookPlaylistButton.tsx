import { useValues } from 'kea'

import { IconNotebook } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useNotebookNode } from 'scenes/notebooks/Nodes/NotebookNodeContext'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

export function QuillInsertInNotebookPlaylistButton({ size }: { size: 'small' | 'normal' }): JSX.Element | null {
    const { sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    const nodeLogic = useNotebookNode()

    if (size !== 'normal' || nodeLogic?.props.nodeType !== NotebookNodeType.RecordingPlaylist) {
        return null
    }

    return (
        <Button
            size="icon-sm"
            tooltip="Comment in a notebook"
            aria-label="Comment in a notebook"
            onClick={() =>
                nodeLogic.actions.insertAfter({ type: NotebookNodeType.Recording, attrs: { id: sessionRecordingId } })
            }
            data-attr="player-meta-add-replay-to-notebook"
        >
            <IconNotebook />
        </Button>
    )
}
