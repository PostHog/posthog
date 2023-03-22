import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { IconJournalPlus } from 'lib/lemon-ui/icons'
import { useActions } from 'kea'
import { NotebookNodeType } from 'scenes/notebooks/Nodes/types'
import { notebookSidebarLogic } from '../Notebook/notebookSidebarLogic'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import './AddToNotebook.scss'

export type AddToNotebookProps = {
    node: NotebookNodeType
    properties: Record<string, any>
    children?: React.ReactNode
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

export function AddToNotebookWrapper({ children, ...props }: AddToNotebookProps): JSX.Element {
    return (
        <div className="AddToNotebookWrapper">
            <FlaggedFeature flag={FEATURE_FLAGS.NOTEBOOKS}>
                <AddToNotebook {...props}>Add to notebook</AddToNotebook>
            </FlaggedFeature>
            {children}
        </div>
    )
}
