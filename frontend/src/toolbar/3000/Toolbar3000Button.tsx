import { useActions, useValues } from 'kea'
import { MenuState, toolbarButtonLogic } from '../button/toolbarButtonLogic'
import { Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { capitalizeFirstLetter } from 'lib/utils'

import './Toolbar3000Button.scss'
import { useLongPress } from 'lib/hooks/useLongPress'
import { FunctionComponent } from 'react'
import React from 'react'

export type Toolbar3000ButtonProps = {
    icon: React.ReactElement | null
    onClick?: () => void
    title?: string
    titleMinimized?: JSX.Element | string
    menuId?: MenuState
}

export const Toolbar3000Button: FunctionComponent<Toolbar3000ButtonProps> = React.forwardRef<
    HTMLDivElement,
    Toolbar3000ButtonProps
>(({ icon, title, onClick, titleMinimized, menuId, ...props }, ref): JSX.Element => {
    const { visibleMenu, minimizedWidth } = useValues(toolbarButtonLogic)
    const { setVisibleMenu } = useActions(toolbarButtonLogic)

    const active = visibleMenu === menuId
    const theTitle = title ?? (menuId ? capitalizeFirstLetter(menuId) : undefined)

    const _onClick = (): void => {
        // TODO: Control the detection of dragging here so that we can appropriately
        // choose whether to fire the event. Also prevent default so we can turn on the "onClickOutside" of the more button
        onClick?.()
        if (menuId) {
            visibleMenu === menuId ? setVisibleMenu('none') : setVisibleMenu(menuId)
        }
    }

    const theButton = (
        <div
            className={clsx('Toolbar3000Button', active && 'Toolbar3000Button--active')}
            aria-label={theTitle}
            ref={ref}
        >
            <button
                className="Toolbar3000Button__button"
                {...props}
                {...useLongPress(
                    (clicked) => {
                        if (clicked) {
                            _onClick()
                        }
                    },
                    {
                        ms: undefined,
                        clickMs: 1 as any,
                        touch: true,
                        click: true,
                    }
                )}
            >
                {icon}
            </button>
        </div>
    )
    return ((minimizedWidth && titleMinimized) || theTitle) && !active ? (
        <Tooltip title={minimizedWidth ? titleMinimized : theTitle}>{theButton}</Tooltip>
    ) : (
        theButton
    )
})

Toolbar3000Button.displayName = 'Toolbar3000Button'
