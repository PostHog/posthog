import { LemonButton } from 'lib/lemon-ui/LemonButton'
import React, { FunctionComponent, ReactElement, useState } from 'react'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import clsx from 'clsx'
import { useValues } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { navigation3000Logic } from '../navigationLogic'
import { LemonTag } from '@posthog/lemon-ui'

export interface NavbarButtonProps {
    identifier: string
    icon: ReactElement
    title?: string
    shortTitle?: string
    tag?: 'alpha' | 'beta'
    onClick?: () => void
    to?: string
    persistentTooltip?: boolean
    active?: boolean
}

export const NavbarButton: FunctionComponent<NavbarButtonProps> = React.forwardRef<
    HTMLButtonElement,
    NavbarButtonProps
>(({ identifier, shortTitle, title, tag, onClick, persistentTooltip, ...buttonProps }, ref): JSX.Element => {
    const { aliasedActiveScene } = useValues(sceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { isNavCollapsed } = useValues(navigation3000Logic)

    const [hasBeenClicked, setHasBeenClicked] = useState(false)

    const isUsingNewNav = featureFlags[FEATURE_FLAGS.POSTHOG_3000_NAV]
    const here = aliasedActiveScene === identifier

    if (!isUsingNewNav) {
        buttonProps.active = here
    }

    let content: JSX.Element | string | undefined
    if (!isUsingNewNav && !isNavCollapsed) {
        content = shortTitle || title
        if (tag) {
            if (tag === 'alpha') {
                content = (
                    <>
                        {content}
                        <LemonTag type="completion" size="small" className="ml-2">
                            ALPHA
                        </LemonTag>
                    </>
                )
            } else if (tag === 'beta') {
                content = (
                    <>
                        {content}
                        <LemonTag type="warning" size="small" className="ml-2">
                            BETA
                        </LemonTag>
                    </>
                )
            }
        }
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
                    {content}
                </LemonButton>
            </Tooltip>
        </li>
    )
})
NavbarButton.displayName = 'NavbarButton'
