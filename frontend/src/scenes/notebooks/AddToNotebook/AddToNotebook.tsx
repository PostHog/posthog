import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconJournalPlus } from 'lib/lemon-ui/icons'
import { useActions } from 'kea'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { NodeType } from 'scenes/notebooks/Nodes/types'

export type AddToNotebookProps = {
    node: NodeType
    properties: Record<string, any>
}

export function AddToNotebook({ node, properties }: AddToNotebookProps): JSX.Element {
    const { addNodeToNotebook } = useActions(notebookLogic)

    return (
        <LemonButton
            onClick={() => {
                addNodeToNotebook(node, properties)
            }}
            size="small"
            tooltip="Add to notebook"
        >
            <IconJournalPlus className="text-lg" />
        </LemonButton>
    )
}
