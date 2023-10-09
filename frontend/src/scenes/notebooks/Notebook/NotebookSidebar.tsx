import { LemonWidget } from 'lib/lemon-ui/LemonWidget'
import { BuiltLogic, useActions, useValues } from 'kea'
import clsx from 'clsx'
import { notebookLogic } from './notebookLogic'
import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'
import { NotebookHistory } from './NotebookHistory'
import { LemonButton } from '@posthog/lemon-ui'
import { IconEyeVisible } from 'lib/lemon-ui/icons'

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
    const { updateAttributes } = useActions(logic)

    return Settings ? <Settings attributes={nodeAttributes} updateAttributes={updateAttributes} /> : null
}

const NotebookSidebarSettings = ({ children }: { children: React.ReactNode }): JSX.Element => {
    return <div className="space-y-2 w-full">{children}</div>
}

export const NotebookSidebarWidget = ({ label, children }: { label: string; children: JSX.Element }): JSX.Element => {
    const { editingNodeLogic } = useValues(notebookLogic)
    const { setEditingNodeId } = useActions(notebookLogic)
    const { selectNode } = useActions(editingNodeLogic as BuiltLogic<notebookNodeLogicType>)

    return (
        <LemonWidget
            title={label}
            collapsible={false}
            actions={
                <>
                    <LemonButton icon={<IconEyeVisible />} size="small" status="primary" onClick={selectNode} />
                    <LemonButton size="small" status="primary" onClick={() => setEditingNodeId(null)}>
                        Done
                    </LemonButton>
                </>
            }
            className="NotebookSidebar__widget"
        >
            {children}
        </LemonWidget>
    )
}

NotebookSidebar.Settings = NotebookSidebarSettings
NotebookSidebar.Widget = NotebookSidebarWidget

export default NotebookSidebar
