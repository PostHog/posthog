import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { IconJournalPlus } from 'lib/lemon-ui/icons'
import { useActions } from 'kea'
import { NotebookNodeType } from '~/types'
import { notebookSidebarLogic } from '../Notebook/notebookSidebarLogic'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'

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
        <FlaggedFeature flag={FEATURE_FLAGS.NOTEBOOKS} match>
            <LemonButton
                data-attr="add-to-notebook"
                onClick={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    addNodeToNotebook(node, properties)
                }}
                tooltip="Add to notebook"
                icon={icon}
                {...buttonProps}
            >
                {children}
            </LemonButton>
        </FlaggedFeature>
    )
}
