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

const Widgets = ({ logic }: { logic: BuiltLogic<notebookNodeLogicType> }): JSX.Element | null => {
    const { setEditingNodeId } = useActions(notebookLogic)
    const { widgets, nodeAttributes } = useValues(logic)
    const { updateAttributes, selectNode } = useActions(logic)

    return (
        <div className="NotebookNodeSettings__widgets space-y-2 w-full">
            {widgets.map(({ key, label, Component }) => (
                <LemonWidget
                    key={key}
                    title={label ?? `Editing '${nodeAttributes.title}'`}
                    collapsible={false}
                    actions={
                        <>
                            <LemonButton
                                icon={<IconEyeVisible />}
                                size="small"
                                status="primary"
                                onClick={() => selectNode()}
                            />
                            <LemonButton size="small" status="primary" onClick={() => setEditingNodeId(null)}>
                                Done
                            </LemonButton>
                        </>
                    }
                >
                    <div className="NotebookNodeSettings__widgets__content">
                        <Component attributes={nodeAttributes} updateAttributes={updateAttributes} />
                    </div>
                </LemonWidget>
            ))}
        </div>
    )
}
