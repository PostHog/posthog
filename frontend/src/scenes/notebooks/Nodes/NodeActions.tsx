import { LemonButton } from '@posthog/lemon-ui'
import { LemonWidget } from 'lib/lemon-ui/LemonWidget'
import { Popover } from 'lib/lemon-ui/Popover'
import { IconClose } from 'lib/lemon-ui/icons'
import { useState } from 'react'
import { createPortal } from 'react-dom'
import { NotebookSettings } from '../Notebook/NotebookSettings'
import { useActions, useValues } from 'kea'
import { notebookNodeLogic } from './notebookNodeLogic'

export const NodeActions = (): JSX.Element => {
    const { widgets, openWidgets, nodeAttributes, unopenWidgets } = useValues(notebookNodeLogic)
    const { deleteNode, addActiveWidget, removeActiveWidget, updateAttributes } = useActions(notebookNodeLogic)

    const collapsed = true

    const widgetOptions = !collapsed ? unopenWidgets : widgets

    return (
        <div className="NotebookNodeActions space-y-1">
            {widgetOptions.map(({ key, label, icon, Component }) => (
                <ActionButton
                    key={key}
                    label={label}
                    icon={icon}
                    onSelectAction={() => addActiveWidget(key)}
                    collapsed={collapsed}
                >
                    <Component attributes={nodeAttributes} updateAttributes={updateAttributes} />
                </ActionButton>
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
            {openWidgets.length > 0
                ? createPortal(
                      <NotebookSettings
                          widgets={openWidgets}
                          attributes={nodeAttributes}
                          updateAttributes={updateAttributes}
                          onDismiss={removeActiveWidget}
                      />,
                      document.getElementsByClassName('NotebookSettings__portal')[0]
                  )
                : null}
        </div>
    )
}

const ActionButton = ({
    label,
    icon,
    collapsed,
    onSelectAction,
    children,
}: {
    label: string
    icon: JSX.Element
    collapsed: boolean
    onSelectAction: () => void
    children: React.ReactChild
}): JSX.Element => {
    const [visible, setVisible] = useState<boolean>(false)

    return (
        <Popover
            visible={visible}
            placement="right"
            onClickOutside={() => setVisible(false)}
            className="NotebookNodeActions__popover"
            overlay={
                <LemonWidget title={label} closable={false}>
                    {children}
                </LemonWidget>
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                tooltip={label}
                tooltipPlacement="left"
                icon={icon}
                onClick={collapsed ? () => setVisible(true) : onSelectAction}
            />
        </Popover>
    )
}
