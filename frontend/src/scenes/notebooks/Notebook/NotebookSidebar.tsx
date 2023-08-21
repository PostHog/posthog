import { LemonWidget } from 'lib/lemon-ui/LemonWidget'
import { BuiltLogic, useActions, useValues } from 'kea'
import clsx from 'clsx'
import { notebookLogic } from './notebookLogic'
import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'

export const NotebookSidebar = (): JSX.Element | null => {
    const { selectedNodeLogic, isShowingSidebar } = useValues(notebookLogic)

    return (
        <div
            className={clsx('NotebookSidebar', {
                'NotebookSidebar--showing': isShowingSidebar,
            })}
        >
            <div className="NotebookSidebar__content">{selectedNodeLogic && <Widgets logic={selectedNodeLogic} />}</div>
        </div>
    )
}

export const Widgets = ({ logic }: { logic: BuiltLogic<notebookNodeLogicType> }): JSX.Element | null => {
    const { widgets, nodeAttributes } = useValues(logic)
    const { updateAttributes } = useActions(logic)

    if (widgets.length === 0) {
        return null
    }

    return (
        <div className="NotebookNodeSettings__widgets space-y-2 w-full max-w-80">
            {widgets.map(({ key, label, Component }) => (
                <LemonWidget key={key} title={label}>
                    <Component attributes={nodeAttributes} updateAttributes={updateAttributes} />
                </LemonWidget>
            ))}
        </div>
    )
}
