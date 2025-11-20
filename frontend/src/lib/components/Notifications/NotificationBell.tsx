import { useValues } from 'kea'
import { useState } from 'react'

import { useNotificationsWebSocket } from 'lib/hooks/useNotificationsWebSocket'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover'
import { IconBell, IconWithCount } from 'lib/lemon-ui/icons'
import { notificationsLogic } from 'lib/logic/notificationsLogic'

import { NotificationsList } from './NotificationsList'

export function NotificationBell(): JSX.Element {
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
                    <NotificationsList />
                </div>
            }
            placement="bottom-end"
        >
            <LemonButton
                icon={
                    unreadCount > 0 ? (
                        <IconWithCount count={unreadCount} status="primary">
                            <IconBell />
                        </IconWithCount>
                    ) : (
                        <IconBell />
                    )
                }
                size="small"
                onClick={() => setIsOpen(!isOpen)}
                aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ''}`}
                data-attr="notifications-bell"
            />
        </Popover>
    )
}
