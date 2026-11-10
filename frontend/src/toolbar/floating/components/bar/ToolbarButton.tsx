import './ToolbarButton.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { FunctionComponent, useEffect } from 'react'
import React from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils/strings'

import { MenuState, toolbarLogic } from '../../../shared/bar/toolbarLogic'

export type ToolbarButtonProps = {
    children: React.ReactNode
    onClick?: () => void
    title?: string
    titleMinimized?: string
    menuId?: MenuState
    flex?: boolean
}

export const ToolbarButton: FunctionComponent<ToolbarButtonProps> = React.forwardRef<
    HTMLDivElement,
    ToolbarButtonProps
>(({ children, title, onClick, titleMinimized, menuId, flex, ...props }, ref): JSX.Element => {
    const { visibleMenu, minimized, isDragging } = useValues(toolbarLogic)
    const { setVisibleMenu } = useActions(toolbarLogic)

    const active = visibleMenu === menuId
    const theTitle = title ?? (menuId ? capitalizeFirstLetter(menuId) : undefined)
    const label = (minimized && titleMinimized) || theTitle

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
            setVisibleMenu(visibleMenu === menuId ? 'none' : menuId)
        }
    }

    const theButton = (
        <div
            className={clsx('ToolbarButton', active && 'ToolbarButton--active', flex && 'ToolbarButton--flex')}
            ref={ref}
        >
            <button className="ToolbarButton__button" aria-label={label} {...props} onClick={_onClick}>
                {children}
            </button>
        </div>
    )

    return label && !isDragging ? <Tooltip title={label}>{theButton}</Tooltip> : theButton
})

ToolbarButton.displayName = 'ToolbarButton'
