import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { IconJournalPlus } from 'lib/lemon-ui/icons'
import { useActions } from 'kea'
import { NotebookNodeType } from 'scenes/notebooks/Nodes/types'
import { notebookSidebarLogic } from '../Notebook/notebookSidebarLogic'

export type AddToNotebookProps = {
    node: NotebookNodeType
    properties: Record<string, any>
} & LemonButtonProps

export function AddToNotebook({
    node,
    properties,
    icon = <IconJournalPlus className="text-lg" />,
    children,
    ...buttonProps
}: AddToNotebookProps): JSX.Element {
    const { addNodeToNotebook } = useActions(notebookSidebarLogic)

    return (
        <LemonButton
            data-attr="add-to-notebook"
            onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
                addNodeToNotebook(node, properties)
            }}
            size="small"
            tooltip="Add to notebook"
            {...buttonProps}
        >
            {children}
            {icon}
        </LemonButton>
    )
}
