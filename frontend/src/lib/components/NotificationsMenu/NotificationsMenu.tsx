import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconNotification } from '@posthog/icons'

import { notificationsMenuLogic } from 'lib/components/NotificationsMenu/notificationsMenuLogic'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import { cn } from 'lib/utils/css-classes'

import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'

export const NotificationsMenu = ({ iconOnly = false }: { iconOnly?: boolean }): JSX.Element => {
    const { isNotificationsPanelActive } = useValues(notificationsMenuLogic)
    const { toggleNotificationsPanel } = useActions(notificationsMenuLogic)
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

    return (
        <ButtonPrimitive
            tooltip={iconOnly ? 'Notifications' : undefined}
            tooltipPlacement="right"
            tooltipCloseDelayMs={0}
            iconOnly={iconOnly}
            menuItem={!iconOnly}
            active={isNotificationsPanelActive}
            onClick={() => toggleNotificationsPanel('bell')}
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
