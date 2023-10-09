import { LemonWidget } from 'lib/lemon-ui/LemonWidget'
import { BuiltLogic, useActions, useValues } from 'kea'
import clsx from 'clsx'
import { notebookLogic } from './notebookLogic'
import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'
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

const Widgets = ({ logic }: { logic: BuiltLogic<notebookNodeLogicType> }): JSX.Element | null => {
    const { nodeAttributes, settings: Settings } = useValues(logic)
    const { updateAttributes, selectNode } = useActions(logic)
    const { setEditingNodeId } = useActions(notebookLogic)

    return Settings ? (
        <Settings
            attributes={nodeAttributes}
            updateAttributes={updateAttributes}
            close={() => setEditingNodeId(null)}
            selectNode={selectNode}
        />
    ) : null
}

const NotebookSidebarWidgets = ({ children }: { children: React.ReactNode }): JSX.Element => {
    return <div className="NotebookNodeSettings__widgets space-y-2 w-full">{children}</div>
}

export const NotebookSidebarWidget = ({
    label,
    actions,
    children,
}: {
    label: string
    actions: JSX.Element
    children: JSX.Element
}): JSX.Element => {
    return (
        <LemonWidget title={label} collapsible={false} actions={actions}>
            {children}
        </LemonWidget>
    )
}

NotebookSidebar.Widgets = NotebookSidebarWidgets
NotebookSidebar.Widget = NotebookSidebarWidget

export default NotebookSidebar
