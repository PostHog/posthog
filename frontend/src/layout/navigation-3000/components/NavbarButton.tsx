import { LemonButton } from 'lib/lemon-ui/LemonButton'
import React, { FunctionComponent, ReactElement, useState } from 'react'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import clsx from 'clsx'

export interface NavbarButtonProps {
    identifier: string
    icon: ReactElement
    title?: string
    onClick?: () => void
    to?: string
    persistentTooltip?: boolean
    active?: boolean
    here?: boolean
}

export const NavbarButton: FunctionComponent<NavbarButtonProps> = React.forwardRef<
    HTMLButtonElement,
    NavbarButtonProps
>(({ identifier, title, onClick, persistentTooltip, here, ...buttonProps }, ref): JSX.Element => {
    const [hasBeenClicked, setHasBeenClicked] = useState(false)

    return (
        <li>
            <Tooltip
                title={here ? `${title} (you are here)` : title}
                placement="right"
                delayMs={0}
                visible={!persistentTooltip && hasBeenClicked ? false : undefined} // Force-hide tooltip after button click
            >
                <LemonButton
                    ref={ref}
                    data-attr={`menu-item-${identifier.toString().toLowerCase()}`}
                    onMouseEnter={() => setHasBeenClicked(false)}
                    onClick={() => {
                        setHasBeenClicked(true)
                        onClick?.()
                    }}
                    className={clsx('NavbarButton', here && 'NavbarButton--here')}
                    {...buttonProps}
                />
            </Tooltip>
        </li>
    )
})
NavbarButton.displayName = 'NavbarButton'
