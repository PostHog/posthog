import { LemonWidget } from 'lib/lemon-ui/LemonWidget'
import { BuiltLogic, useActions, useValues } from 'kea'
import clsx from 'clsx'
import { notebookLogic } from './notebookLogic'
import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'
import { LemonButton } from '@posthog/lemon-ui'
import { IconEyeVisible } from 'lib/lemon-ui/icons'
import { NotebookHistory } from './NotebookHistory'

export const NotebookSidebar = (): JSX.Element | null => {
    const { editingNodeLogic, isShowingSidebar, showHistory } = useValues(notebookLogic)

    return (
        <div
            className={clsx('NotebookSidebar', {
                'NotebookSidebar--showing': isShowingSidebar,
            })}
        >
            <div className="NotebookSidebar__content">
                {isShowingSidebar ? (
                    editingNodeLogic ? (
                        <Widgets logic={editingNodeLogic} />
                    ) : showHistory ? (
                        <NotebookHistory />
                    ) : null
                ) : null}
            </div>
        </div>
    )
}

const Widgets = ({ logic }: { logic: BuiltLogic<notebookNodeLogicType> }): JSX.Element => {
    const { setEditingNodeId } = useActions(notebookLogic)
    const { settings: Settings, nodeAttributes, title } = useValues(logic)
    const { updateAttributes, selectNode } = useActions(logic)

    return (
        <LemonWidget
            title={`Editing '${title}'`}
            className="NotebookSidebar__widget"
            actions={
                <>
                    <LemonButton icon={<IconEyeVisible />} size="small" status="primary" onClick={() => selectNode()} />
                    <LemonButton size="small" status="primary" onClick={() => setEditingNodeId(null)}>
                        Done
                    </LemonButton>
                </>
            }
        >
            {Settings ? (
                <Settings key={nodeAttributes.nodeId} attributes={nodeAttributes} updateAttributes={updateAttributes} />
            ) : null}
        </LemonWidget>
    )
}
