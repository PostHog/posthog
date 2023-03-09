import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconJournalPlus } from 'lib/lemon-ui/icons'
import { useActions } from 'kea'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { NodeType } from 'scenes/notebooks/Nodes/types'
import { SessionRecordingPlayerLogicProps } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

export function AddToNotebook({ sessionRecordingId }: SessionRecordingPlayerLogicProps): JSX.Element {
    const { addNodeToNotebook } = useActions(notebookLogic)

    return (
        <LemonButton
            onClick={() => {
                addNodeToNotebook(NodeType.Recording, { sessionRecordingId })
            }}
            size="small"
            tooltip="Add to notebook"
        >
            <IconJournalPlus className="text-lg" />
        </LemonButton>
    )
}
