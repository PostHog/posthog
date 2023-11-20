import { useActions, useValues } from 'kea'
import { MenuState, toolbarButtonLogic } from './toolbarButtonLogic'
import { Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { capitalizeFirstLetter } from 'lib/utils'

import './ToolbarButton.scss'
import { FunctionComponent } from 'react'
import React from 'react'

export type ToolbarButtonProps = {
    icon: React.ReactElement | null
    onClick?: () => void
    title?: string
    titleMinimized?: JSX.Element | string
    menuId?: MenuState
}

export const ToolbarButton: FunctionComponent<ToolbarButtonProps> = React.forwardRef<
    HTMLDivElement,
    ToolbarButtonProps
>(({ icon, title, onClick, titleMinimized, menuId, ...props }, ref): JSX.Element => {
    const { visibleMenu, minimized, isDragging } = useValues(toolbarButtonLogic)
    const { setVisibleMenu } = useActions(toolbarButtonLogic)

    const active = visibleMenu === menuId
    const theTitle = title ?? (menuId ? capitalizeFirstLetter(menuId) : undefined)

    const _onClick = (e: React.MouseEvent<HTMLButtonElement, MouseEvent>): void => {
        if (isDragging) {
            return
        }

        e.preventDefault()

        onClick?.()
        if (menuId) {
            visibleMenu === menuId ? setVisibleMenu('none') : setVisibleMenu(menuId)
        }
    }

    const theButton = (
        <div className={clsx('ToolbarButton', active && 'ToolbarButton--active')} aria-label={theTitle} ref={ref}>
            <button className="ToolbarButton__button" {...props} onClick={_onClick}>
                {icon}
            </button>
        </div>
    )
    return ((minimized && titleMinimized) || theTitle) && !active && !isDragging ? (
        <Tooltip title={minimized ? titleMinimized : theTitle}>{theButton}</Tooltip>
    ) : (
        theButton
    )
})

ToolbarButton.displayName = 'ToolbarButton'
