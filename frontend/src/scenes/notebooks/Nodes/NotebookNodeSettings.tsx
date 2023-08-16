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
    const ref = useRef<HTMLDivElement>(null)

    return (
        <div className="testdavid" ref={ref}>
            {createPortal(
                <NodeActions positionTop={ref.current?.getBoundingClientRect().top} />,
                document.getElementsByClassName('NotebookNodeSettingActions__portal')[0]
            )}
            {createPortal(<WidgetSettings />, document.getElementsByClassName('NotebookNodeSettingWidgets__portal')[0])}
        </div>
    )
}

const NodeActions = ({ positionTop }: { positionTop: number | undefined }): JSX.Element => {
    const { widgets, unopenWidgets } = useValues(notebookNodeLogic)
    const { deleteNode } = useActions(notebookNodeLogic)

    const actionsRef = useRef<HTMLDivElement>(null)
    const { width } = useResizeObserver({ ref: actionsRef })

    const collapsed = !!width && width < 140

    const selectableWidgets = collapsed ? widgets : unopenWidgets

    return (
        <div
            ref={actionsRef}
            className="flex w-full flex-col items-end"
            style={{ position: 'absolute', top: positionTop }}
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
            className="NotebookNodeActions__popover"
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

export const WidgetSettings = (): JSX.Element | null => {
    const { openWidgets, nodeAttributes } = useValues(notebookNodeLogic)
    const { updateAttributes, removeActiveWidget } = useActions(notebookNodeLogic)

    if (openWidgets.length === 0) {
        return null
    }

    return (
        <div className="NotebookSettings space-y-2">
            {openWidgets.map(({ key, label, Component }) => (
                <LemonWidget key={key} title={label} onClose={() => removeActiveWidget(key)}>
                    <Component attributes={nodeAttributes} updateAttributes={updateAttributes} />
                </LemonWidget>
            ))}
        </div>
    )
}
