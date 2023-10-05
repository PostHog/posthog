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
        <div className="NotebookNodeSettings__widgets space-y-2 w-full flex flex-col">
            {widgets.map(({ key, label, scrollable, Component }, index) => (
                <LemonWidget
                    key={key}
                    title={label ?? `Editing '${nodeAttributes.title}'`}
                    scrollable={scrollable}
                    actions={
                        index === 0 ? (
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
                        ) : null
                    }
                >
                    <Component attributes={nodeAttributes} updateAttributes={updateAttributes} />
                </LemonWidget>
            ))}
        </div>
    )
}
