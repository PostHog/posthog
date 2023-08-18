import { LemonButton } from '@posthog/lemon-ui'
import { LemonWidget } from 'lib/lemon-ui/LemonWidget'
import { Popover } from 'lib/lemon-ui/Popover'
import { IconClose } from 'lib/lemon-ui/icons'
import { useRef, useState } from 'react'
import { BuiltLogic, useActions, useValues } from 'kea'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { NotebookNodeWidget } from '../Notebook/utils'
import { notebookNodeLogic } from '../Nodes/notebookNodeLogic'
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

export const Actions = (): JSX.Element => {
    const { widgets, unopenWidgets, domNode } = useValues(notebookNodeLogic)
    const { deleteNode } = useActions(notebookNodeLogic)

    const ref = useRef<HTMLDivElement>(null)
    const { height, width } = useResizeObserver({ ref })

    const collapsed = !!width && width < 320
    const selectableWidgets = collapsed ? widgets : unopenWidgets
    const verticalOffset = domNode.offsetTop + domNode.offsetHeight - (height || 0)

    return (
        <div ref={ref} className="flex w-full flex-col items-end space-y-1 absolute" style={{ top: verticalOffset }}>
            {selectableWidgets.map((widget) => (
                <WidgetButton key={widget.key} widget={widget} collapsed={collapsed} />
            ))}
            <LemonButton
                type="secondary"
                status="danger"
                size="small"
                tooltip="Settings"
                tooltipPlacement="right"
                icon={<IconClose />}
                onClick={deleteNode}
            />
        </div>
    )
}

const WidgetButton = ({
    widget: { label, key, icon, Component },
    collapsed,
}: {
    widget: NotebookNodeWidget
    collapsed: boolean
}): JSX.Element => {
    const { nodeAttributes } = useValues(notebookNodeLogic)
    const { updateAttributes, addActiveWidget } = useActions(notebookNodeLogic)
    const [visible, setVisible] = useState<boolean>(false)

    return (
        <Popover
            visible={visible}
            placement="right"
            onClickOutside={() => setVisible(false)}
            className="NotebookNodeSetting__actions__popover"
            overlay={
                <LemonWidget title={label} collapsible={false}>
                    <Component attributes={nodeAttributes} updateAttributes={updateAttributes} />
                </LemonWidget>
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                tooltip={label}
                tooltipPlacement="left"
                icon={icon}
                onClick={() => (collapsed ? setVisible(true) : addActiveWidget(key))}
            />
        </Popover>
    )
}

export const Widgets = ({ logic }: { logic: BuiltLogic<notebookNodeLogicType> }): JSX.Element | null => {
    const { unopenWidgets, nodeAttributes } = useValues(logic)
    const { updateAttributes, removeActiveWidget } = useActions(logic)

    if (unopenWidgets.length === 0) {
        return null
    }

    return (
        <div className="NotebookNodeSettings__widgets space-y-2 w-full max-w-80">
            {unopenWidgets.map(({ key, label, Component }) => (
                <LemonWidget key={key} title={label} onClose={() => removeActiveWidget(key)}>
                    <Component attributes={nodeAttributes} updateAttributes={updateAttributes} />
                </LemonWidget>
            ))}
        </div>
    )
}
