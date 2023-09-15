import { LemonWidget } from 'lib/lemon-ui/LemonWidget'
import { BuiltLogic, useActions, useValues } from 'kea'
import clsx from 'clsx'
import { notebookLogic } from './notebookLogic'
import { notebookNodeLogicType } from '../Nodes/notebookNodeLogicType'

export const NotebookSidebar = (): JSX.Element | null => {
    const { selectedNodeLogic, isShowingSidebar, isEditable } = useValues(notebookLogic)
    const { setIsShowingSidebar } = useActions(notebookLogic)

    if (!isEditable) {
        return null
    }

    return (
        <div
            className={clsx('NotebookSidebar', {
                'NotebookSidebar--showing': isShowingSidebar,
            })}
        >
            <div className="NotebookSidebar__content">
                {selectedNodeLogic && isShowingSidebar && (
                    <Widgets logic={selectedNodeLogic} onClose={() => setIsShowingSidebar(false)} />
                )}
            </div>
        </div>
    )
}

export const Widgets = ({
    logic,
    onClose,
}: {
    logic: BuiltLogic<notebookNodeLogicType>
    onClose: () => void
}): JSX.Element | null => {
    const { widgets, nodeAttributes } = useValues(logic)
    const { updateAttributes } = useActions(logic)

    return (
        <div className="NotebookNodeSettings__widgets space-y-2 w-full">
            {widgets.map(({ key, label, Component }) => (
                <LemonWidget key={key} title={label} collapsible={false} onClose={onClose}>
                    <div className="NotebookNodeSettings__widgets__content">
                        <Component attributes={nodeAttributes} updateAttributes={updateAttributes} />
                    </div>
                </LemonWidget>
            ))}
        </div>
    )
}
