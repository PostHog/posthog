import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconNotification } from '@posthog/icons'

import { IconWithCount } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import { cn } from 'lib/utils/css-classes'

import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

export const NotificationsMenu = ({ iconOnly = false }: { iconOnly?: boolean }): JSX.Element => {
    const { activePanelIdentifier, isLayoutPanelVisible } = useValues(panelLayoutLogic)
    const { setActivePanelIdentifier, showLayoutPanel, closePanel } = useActions(panelLayoutLogic)
    const { inAppUnreadCount } = useValues(sidePanelNotificationsLogic)
    const [badgePulse, setBadgePulse] = useState(false)
    const prevCountRef = useRef(inAppUnreadCount)

    useEffect(() => {
        if (inAppUnreadCount !== prevCountRef.current) {
            prevCountRef.current = inAppUnreadCount
            setBadgePulse(true)
            const timer = setTimeout(() => setBadgePulse(false), 300)
            return () => clearTimeout(timer)
        }
    }, [inAppUnreadCount])

    const isActive = isLayoutPanelVisible && activePanelIdentifier === 'Notifications'

    const handleClick = (): void => {
        if (isActive) {
            closePanel()
        } else {
            setActivePanelIdentifier('Notifications')
            showLayoutPanel(true)
        }
    }

    return (
        <ButtonPrimitive
            tooltip={iconOnly ? 'Notifications' : undefined}
            tooltipPlacement="right"
            tooltipCloseDelayMs={0}
            iconOnly={iconOnly}
            menuItem={!iconOnly}
            active={isActive}
            onClick={handleClick}
            className="group"
            data-attr="notifications-menu-button"
        >
            <span
                className={cn(
                    'flex text-secondary group-hover:text-primary transition-transform duration-300',
                    badgePulse ? 'scale-125' : 'scale-100'
                )}
            >
                <IconWithCount count={inAppUnreadCount} size="xsmall">
                    <IconNotification className="size-4.5" />
                </IconWithCount>
            </span>
            {!iconOnly && (
                <>
                    <span className="-ml-[2px]">Notifications</span>
                    <MenuOpenIndicator direction="right" />
                </>
            )}
        </ButtonPrimitive>
    )
}
