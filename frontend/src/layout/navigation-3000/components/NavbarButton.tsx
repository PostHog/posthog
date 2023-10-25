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
    shortTitle?: string
    onClick?: () => void
    to?: string
    persistentTooltip?: boolean
    active?: boolean
}

export const NavbarButton: FunctionComponent<NavbarButtonProps> = React.forwardRef<
    HTMLButtonElement,
    NavbarButtonProps
>(({ identifier, shortTitle, title, onClick, persistentTooltip, ...buttonProps }, ref): JSX.Element => {
    const { aliasedActiveScene } = useValues(sceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const [hasBeenClicked, setHasBeenClicked] = useState(false)

    const isUsingNewNav = featureFlags[FEATURE_FLAGS.POSTHOG_3000_NAV]
    const here = aliasedActiveScene === identifier

    if (!isUsingNewNav) {
        buttonProps.active = here
    }

    return (
        <li className="w-full">
            <Tooltip
                title={isUsingNewNav ? (here ? `${title} (you are here)` : title) : null}
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
                    className={clsx('NavbarButton', isUsingNewNav && here && 'NavbarButton--here')}
                    fullWidth
                    {...buttonProps}
                >
                    {!isUsingNewNav ? shortTitle || title : null}
                </LemonButton>
            </Tooltip>
        </li>
    )
})
NavbarButton.displayName = 'NavbarButton'
