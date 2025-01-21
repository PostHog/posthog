import { LemonSkeleton, LemonTag } from '@posthog/lemon-ui'
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

// Guarantee that if `shortTitle` is not provided, we'll guarantee `title` is a string
type TitleProps = { shortTitle: string; title: string | ReactElement } | { shortTitle?: never; title: string }

interface NavbarProps extends Pick<LemonButtonProps, 'onClick' | 'icon' | 'sideIcon' | 'to' | 'active'> {
    identifier: string
    icon: ReactElement
    forceTooltipOnHover?: boolean
    tag?: 'alpha' | 'beta' | 'new'
    sideAction?: NavbarItem['sideAction']
}

export type NavbarButtonProps = TitleProps &
    NavbarProps &
    Pick<LemonButtonProps, 'onClick' | 'icon' | 'sideIcon' | 'to' | 'active'>

export const NavbarButton: FunctionComponent<NavbarButtonProps> = React.forwardRef<
    HTMLButtonElement,
    NavbarButtonProps
>(({ identifier, shortTitle, title, forceTooltipOnHover, tag, onClick, sideAction, ...rest }, ref): JSX.Element => {
    const { activeScene } = useValues(sceneLogic)
    const { sceneBreadcrumbKeys } = useValues(breadcrumbsLogic)
    const { hideNavOnMobile } = useActions(navigation3000Logic)
    const { isNavCollapsed } = useValues(navigation3000Logic)
    const isUsingNewNav = useFeatureFlag('POSTHOG_3000_NAV')

    const [hasBeenClicked, setHasBeenClicked] = useState(false)

    const here = activeScene === identifier || sceneBreadcrumbKeys.includes(identifier)
    const isNavCollapsedActually = isNavCollapsed || isUsingNewNav

    const [notices, onAcknowledged] = useSidebarChangeNotices({ identifier })

    // Simple skeleton for Storybook to create anonymous navbar buttons
    if (process.env.STORYBOOK && !here) {
        // Multiple of 4 because not all `w-${number}` values are available
        const width = Math.floor(((typeof title === 'string' ? title.length : shortTitle?.length ?? 10) * 2) / 4) * 4

        return (
            <li className="w-full">
                <LemonSkeleton active={false} className={clsx('h-8 my-1 w-', `w-${width}`)} />
            </li>
        )
    }

    const buttonProps: LemonButtonProps = rest
    if (!isUsingNewNav) {
        buttonProps.active = here
    }

    let content: JSX.Element | string | undefined
    if (!isNavCollapsedActually) {
        content = shortTitle != null ? shortTitle : title
        if (tag) {
            content = (
                <>
                    <span className="grow">{content}</span>
                    <LemonTag
                        type={tag === 'alpha' ? 'completion' : tag === 'beta' ? 'warning' : 'success'}
                        size="small"
                        className="ml-2"
                    >
                        {tag.toUpperCase()}
                    </LemonTag>
                </>
            )
        }

        if (sideAction) {
            // @ts-expect-error - in this case we are perfectly okay with assigning a sideAction
            buttonProps.sideAction = {
                ...sideAction,
                divider: true,
                'data-attr': `menu-item-${sideAction.identifier.toLowerCase()}`,
            }
            buttonProps.sideIcon = null
        }
    } else {
        buttonProps.sideIcon = null
    }

    const buttonContent =
        process.env.STORYBOOK && !here ? (
            <LemonSkeleton className={clsx('h-3', `w-${shortTitle?.length ?? 10}`)} />
        ) : (
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
                status="alt"
                {...buttonProps}
            >
                {content}
            </LemonButton>
        )

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
                            ? here && typeof title === 'string'
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
})
NavbarButton.displayName = 'NavbarButton'
