import { LemonButton } from '@posthog/lemon-ui'
import { LemonWidget } from 'lib/lemon-ui/LemonWidget'
import { Popover } from 'lib/lemon-ui/Popover'
import { IconClose } from 'lib/lemon-ui/icons'
import { useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useActions, useValues } from 'kea'
import { notebookNodeLogic } from './notebookNodeLogic'
import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { NotebookNodeWidget } from '../Notebook/utils'

export const NotebookNodeSettings = (): JSX.Element => {
    return (
        <div>
            {createPortal(<Actions />, document.getElementsByClassName('NotebookNodeSetting__actions__portal')[0])}
            {createPortal(<Widgets />, document.getElementsByClassName('NotebookNodeSettings__widgets__portal')[0])}
        </div>
    )
}

const Actions = (): JSX.Element => {
    const { widgets, unopenWidgets, domNode } = useValues(notebookNodeLogic)
    const { deleteNode } = useActions(notebookNodeLogic)

    const ref = useRef<HTMLDivElement>(null)
    const { height, width } = useResizeObserver({ ref })

    const collapsed = !!width && width < 320
    const selectableWidgets = collapsed ? widgets : unopenWidgets
    const verticalOffset = domNode.offsetTop + domNode.offsetHeight - (height || 0)

    return (
        <div
            ref={ref}
            className="flex w-full flex-col items-end space-y-1"
            style={{ position: 'absolute', top: verticalOffset }}
        >
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

export const Widgets = (): JSX.Element | null => {
    const { openWidgets, nodeAttributes } = useValues(notebookNodeLogic)
    const { updateAttributes, removeActiveWidget } = useActions(notebookNodeLogic)

    if (openWidgets.length === 0) {
        return null
    }

    return (
        <div className="NotebookNodeSettings__widgets space-y-2">
            {openWidgets.map(({ key, label, Component }) => (
                <LemonWidget key={key} title={label} onClose={() => removeActiveWidget(key)}>
                    <Component attributes={nodeAttributes} updateAttributes={updateAttributes} />
                </LemonWidget>
            ))}
        </div>
    )
}
