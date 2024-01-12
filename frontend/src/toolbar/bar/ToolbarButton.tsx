import './ToolbarButton.scss'

import { Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'lib/utils'
import { FunctionComponent, useEffect } from 'react'
import React from 'react'

import { MenuState, toolbarLogic } from './toolbarLogic'

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
    const { visibleMenu, minimized, isDragging } = useValues(toolbarLogic)
    const { setVisibleMenu } = useActions(toolbarLogic)

    const active = visibleMenu === menuId
    const theTitle = title ?? (menuId ? capitalizeFirstLetter(menuId) : undefined)

    // We want to delay the cancel of dragging as there is a slight race with the click handler
    const delayedIsDragging = React.useRef<boolean>(false)

    useEffect(() => {
        if (isDragging) {
            delayedIsDragging.current = true
        } else {
            setTimeout(() => {
                delayedIsDragging.current = false
            }, 100)
        }
    }, [isDragging])

    const _onClick = (e: React.MouseEvent<HTMLButtonElement, MouseEvent>): void => {
        if (delayedIsDragging.current) {
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
