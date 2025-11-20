import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCheck, IconGear } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Notification, notificationsLogic } from 'lib/logic/notificationsLogic'
import { urls } from 'scenes/urls'

export function NotificationsList(): JSX.Element {
    const { notifications, notificationsLoading, unreadCount } = useValues(notificationsLogic)
    const { markAsRead, markAllAsRead } = useActions(notificationsLogic)

    return (
        <div className="flex flex-col h-full">
            <div className="flex items-center justify-between p-3 border-b">
                <h3 className="m-0 text-base font-semibold">Notifications</h3>
                <div className="flex gap-2">
                    {unreadCount > 0 && (
                        <LemonButton size="small" type="secondary" onClick={() => markAllAsRead()} icon={<IconCheck />}>
                            Mark all read
                        </LemonButton>
                    )}
                    <Link to={urls.notificationPreferences()}>
                        <LemonButton size="small" type="secondary" icon={<IconGear />} />
                    </Link>
                </div>
            </div>

            <div className="flex-1 overflow-y-auto">
                {notificationsLoading ? (
                    <div className="flex items-center justify-center p-8">
                        <Spinner />
                    </div>
                ) : notifications.length === 0 ? (
                    <div className="flex flex-col items-center justify-center p-8 text-muted-alt">
                        <p className="text-center">No notifications yet</p>
                        <p className="text-xs text-center">When something important happens, you will see it here</p>
                    </div>
                ) : (
                    <div className="divide-y">
                        {notifications.map((notification) => (
                            <NotificationItem
                                key={notification.id}
                                notification={notification}
                                onMarkRead={() => markAsRead(notification.id)}
                            />
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}

interface NotificationItemProps {
    notification: Notification
    onMarkRead: () => void
}

function NotificationItem({ notification, onMarkRead }: NotificationItemProps): JSX.Element {
    const isUnread = !notification.read_at
    const timeAgo = dayjs(notification.created_at).fromNow()

    return (
        <div
            className={clsx('p-3 hover:bg-secondary-highlight cursor-pointer transition-colors', {
                'bg-danger-highlight': isUnread,
            })}
            onClick={onMarkRead}
        >
            <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                        <h4 className="m-0 text-sm font-semibold truncate">{notification.title}</h4>
                        {isUnread && (
                            <span className="px-1.5 py-0.5 text-xs font-medium bg-danger-highlight text-danger rounded">
                                Unread
                            </span>
                        )}
                        {notification.priority === 'urgent' && (
                            <span className="px-1.5 py-0.5 text-xs font-medium bg-danger text-white rounded">
                                Urgent
                            </span>
                        )}
                        {notification.priority === 'high' && (
                            <span className="px-1.5 py-0.5 text-xs font-medium bg-warning text-white rounded">
                                High
                            </span>
                        )}
                    </div>
                    <p className="m-0 mt-1 text-xs text-muted">{notification.message}</p>
                    <p className="m-0 mt-1 text-xs text-muted-alt">{timeAgo}</p>
                </div>
                {isUnread && (
                    <div className="flex-shrink-0">
                        <div className="w-2 h-2 bg-primary rounded-full" title="Unread" />
                    </div>
                )}
            </div>
        </div>
    )
}
