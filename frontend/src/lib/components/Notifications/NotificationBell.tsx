import { useValues } from 'kea'
import { useState } from 'react'

import { useNotificationsWebSocket } from 'lib/hooks/useNotificationsWebSocket'
import { Popover } from 'lib/lemon-ui/Popover'
import { IconBell, IconWithCount } from 'lib/lemon-ui/icons'
import { notificationsLogic } from 'lib/logic/notificationsLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { NotificationsList } from './NotificationsList'

interface NotificationBellProps {
    isLayoutNavCollapsed?: boolean
}

export function NotificationBell({ isLayoutNavCollapsed = false }: NotificationBellProps): JSX.Element {
    const { unreadCount } = useValues(notificationsLogic)
    const [isOpen, setIsOpen] = useState(false)

    // Connect to WebSocket for real-time updates
    useNotificationsWebSocket()

    return (
        <Popover
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            overlay={
                <div className="NotificationsPanel" style={{ width: 400, maxHeight: 600 }}>
                    <NotificationsList onClose={() => setIsOpen(false)} />
                </div>
            }
            placement="bottom-end"
        >
            <ButtonPrimitive
                menuItem={!isLayoutNavCollapsed}
                tooltip={isLayoutNavCollapsed ? 'Notifications' : undefined}
                tooltipPlacement="right"
                iconOnly={isLayoutNavCollapsed}
                onClick={() => setIsOpen(!isOpen)}
                aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ''}`}
                data-attr="notifications-bell"
                active={isOpen}
                className="group"
            >
                <span className="flex text-tertiary group-hover:text-primary">
                    {unreadCount > 0 ? (
                        <IconWithCount count={unreadCount} status="primary">
                            <IconBell />
                        </IconWithCount>
                    ) : (
                        <IconBell />
                    )}
                </span>
                {!isLayoutNavCollapsed && 'Notifications'}
            </ButtonPrimitive>
        </Popover>
    )
}
