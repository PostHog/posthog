import { LemonButton } from 'lib/lemon-ui/LemonButton'
import React, { FunctionComponent, ReactElement, useState } from 'react'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import clsx from 'clsx'
import { useValues } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export interface NavbarButtonProps {
    identifier: string
    icon: ReactElement
    title?: string
    onClick?: () => void
    to?: string
    persistentTooltip?: boolean
    active?: boolean
    popoverMarker?: boolean
}

export const NavbarButton: FunctionComponent<NavbarButtonProps> = React.forwardRef<
    HTMLButtonElement,
    NavbarButtonProps
>(({ identifier, title, onClick, persistentTooltip, popoverMarker, ...buttonProps }, ref): JSX.Element => {
    const { aliasedActiveScene } = useValues(sceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const [hasBeenClicked, setHasBeenClicked] = useState(false)

    const here = featureFlags[FEATURE_FLAGS.POSTHOG_3000_NAV] ? aliasedActiveScene === identifier : false

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
                    className={clsx(
                        'NavbarButton',
                        here && 'NavbarButton--here',
                        popoverMarker && 'NavbarButton--popover'
                    )}
                    {...buttonProps}
                />
            </Tooltip>
        </li>
    )
})
NavbarButton.displayName = 'NavbarButton'
