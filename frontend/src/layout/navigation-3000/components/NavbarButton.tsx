import { LemonTag } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import React, { FunctionComponent, ReactElement, useState } from 'react'
import { sceneLogic } from 'scenes/sceneLogic'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { SidebarChangeNoticeContent, useSidebarChangeNotices } from '~/layout/navigation/SideBar/SidebarChangeNotice'

import { navigation3000Logic } from '../navigationLogic'
import { NavbarItem } from '../types'
import { KeyboardShortcut, KeyboardShortcutProps } from './KeyboardShortcut'

export interface NavbarButtonProps extends Pick<LemonButtonProps, 'onClick' | 'icon' | 'sideIcon' | 'to' | 'active'> {
    identifier: string
    icon: ReactElement
    title?: string
    shortTitle?: string
    forceTooltipOnHover?: boolean
    tag?: 'alpha' | 'beta'
    keyboardShortcut?: KeyboardShortcutProps
    sideAction?: NavbarItem['sideAction']
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
            keyboardShortcut,
            sideAction,
            sideIcon,
            ...rest
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

        const buttonProps: LemonButtonProps = rest
        if (!isUsingNewNav) {
            buttonProps.active = here
        }
        if (sideAction) {
            // @ts-expect-error - in this case we are perfectly okay with assigning a sideAction
            buttonProps.sideAction = {
                ...sideAction,
                divider: true,
                'data-attr': `menu-item-${sideAction.identifier.toLowerCase()}`,
            }
            buttonProps.sideIcon = null
        } else if (!isNavCollapsedActually && keyboardShortcut) {
            buttonProps.sideIcon = (
                <span className="text-xs">
                    <KeyboardShortcut {...keyboardShortcut} />
                </span>
            )
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
                onClick={(e) => {
                    if (buttonProps.to) {
                        hideNavOnMobile()
                    }
                    setHasBeenClicked(true)
                    onClick?.(e)
                }}
                className={clsx('NavbarButton', isUsingNewNav && here && 'NavbarButton--here')}
                fullWidth
                type="secondary"
                stealth={true}
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
                        visible={hasBeenClicked ? false : undefined} // Force-hide tooltip after button click
                    >
                        {buttonContent}
                    </Tooltip>
                )}
            </li>
        )
    }
)
NavbarButton.displayName = 'NavbarButton'
