import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { sceneConfigurations } from 'scenes/scenes'
import React, { FunctionComponent, ReactElement, useState } from 'react'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export interface NavbarButtonProps {
    identifier: string
    icon: ReactElement
    title?: string
    onClick?: () => void
    to?: string
    persistentTooltip?: boolean
    active?: boolean
}

export const NavbarButton: FunctionComponent<NavbarButtonProps> = React.forwardRef<HTMLElement, NavbarButtonProps>(
    ({ identifier, title, onClick, persistentTooltip, ...buttonProps }, ref): JSX.Element => {
        const [hasBeenClicked, setHasBeenClicked] = useState(false)

        const effectiveTitle: string | undefined = title || sceneConfigurations[identifier]?.name

        return (
            <li>
                <Tooltip
                    title={effectiveTitle}
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
                        {...buttonProps}
                    />
                </Tooltip>
            </li>
        )
    }
)
NavbarButton.displayName = 'NavbarButton'
