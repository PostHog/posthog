import { LemonTag } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import React, { FunctionComponent, ReactElement, useState } from 'react'
import { sceneLogic } from 'scenes/sceneLogic'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { SidebarChangeNoticeContent, useSidebarChangeNotices } from '~/layout/navigation/SideBar/SidebarChangeNotice'

import { navigation3000Logic } from '../navigationLogic'
import { KeyboardShortcut, KeyboardShortcutProps } from './KeyboardShortcut'

export interface NavbarButtonProps {
    identifier: string
    icon: ReactElement
    title?: string
    shortTitle?: string
    forceTooltipOnHover?: boolean
    tag?: 'alpha' | 'beta'
    onClick?: () => void
    to?: string
    persistentTooltip?: boolean
    active?: boolean
    keyboardShortcut?: KeyboardShortcutProps
}

export const NavbarButton: FunctionComponent<NavbarButtonProps> = React.forwardRef<
    HTMLButtonElement,
    NavbarButtonProps
>(
    (
        {
            identifier,
            shortTitle,
            title,
            forceTooltipOnHover,
            tag,
            onClick,
            persistentTooltip,
            keyboardShortcut,
            ...buttonProps
        },
        ref
    ): JSX.Element => {
        const { activeScene } = useValues(sceneLogic)
        const { sceneBreadcrumbKeys } = useValues(breadcrumbsLogic)
        const { hideNavOnMobile } = useActions(navigation3000Logic)
        const { isNavCollapsed } = useValues(navigation3000Logic)
        const isUsingNewNav = useFeatureFlag('POSTHOG_3000_NAV')

        const [hasBeenClicked, setHasBeenClicked] = useState(false)

        const here = activeScene === identifier || sceneBreadcrumbKeys.includes(identifier)
        const isNavCollapsedActually = isNavCollapsed || isUsingNewNav

        if (!isUsingNewNav) {
            buttonProps.active = here
        }

        let content: JSX.Element | string | undefined
        if (!isNavCollapsedActually) {
            content = shortTitle || title
            if (tag) {
                if (tag === 'alpha') {
                    content = (
                        <>
                            <span className="grow">{content}</span>
                            <LemonTag type="completion" size="small" className="ml-2">
                                ALPHA
                            </LemonTag>
                        </>
                    )
                } else if (tag === 'beta') {
                    content = (
                        <>
                            <span className="grow">{content}</span>
                            <LemonTag type="warning" size="small" className="ml-2">
                                BETA
                            </LemonTag>
                        </>
                    )
                }
            }
        }

        const buttonContent = (
            <LemonButton
                ref={ref}
                data-attr={`menu-item-${identifier.toString().toLowerCase()}`}
                onMouseEnter={() => setHasBeenClicked(false)}
                onClick={() => {
                    if (buttonProps.to) {
                        hideNavOnMobile()
                    }
                    setHasBeenClicked(true)
                    onClick?.()
                }}
                className={clsx('NavbarButton', isUsingNewNav && here && 'NavbarButton--here')}
                fullWidth
                type="secondary"
                stealth={true}
                sideIcon={
                    !isNavCollapsedActually && keyboardShortcut ? (
                        <span className="text-xs">
                            <KeyboardShortcut {...keyboardShortcut} />
                        </span>
                    ) : null
                }
                {...buttonProps}
            >
                {content}
            </LemonButton>
        )

        const [notices, onAcknowledged] = useSidebarChangeNotices({ identifier })

        return (
            <li className="w-full">
                {notices.length ? (
                    <Tooltip
                        title={<SidebarChangeNoticeContent notices={notices} onAcknowledged={onAcknowledged} />}
                        placement={notices[0].placement ?? 'right'}
                        delayMs={0}
                        visible={true}
                    >
                        {buttonContent}
                    </Tooltip>
                ) : (
                    <Tooltip
                        title={
                            forceTooltipOnHover || isNavCollapsedActually
                                ? here
                                    ? `${title} (you are here)`
                                    : title
                                : null
                        }
                        placement="right"
                        delayMs={0}
                        visible={!persistentTooltip && hasBeenClicked ? false : undefined} // Force-hide tooltip after button click
                    >
                        {buttonContent}
                    </Tooltip>
                )}
            </li>
        )
    }
)
NavbarButton.displayName = 'NavbarButton'
