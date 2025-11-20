import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCheck, IconCheckCircle, IconExternal, IconGear } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconRadioButtonUnchecked } from 'lib/lemon-ui/icons'
import { Notification, notificationsLogic } from 'lib/logic/notificationsLogic'
import { urls } from 'scenes/urls'

/**
 * Generate URL for a notification based on resource type and ID.
 * Returns null if the resource type is not supported or resource_id is missing.
 */
function getNotificationUrl(notification: Notification): string | null {
    const { resource_type } = notification

    switch (resource_type) {
        case 'comment':
        case 'mention':
            const parentType = notification.context?.parent_type || notification.context?.scope?.toLowerCase()
            const parentId = notification.context?.parent_resource_id || notification.context?.item_id

            if (parentType && parentId) {
                const url = getNotificationUrl({
                    ...notification,
                    resource_type: parentType,
                    resource_id: parentId,
                })
                return url
            }
            return null

        default:
            if (notification.context?.slug) {
                const slug = notification.context.slug.split('#')[0]
                return slug
            }
            return null
    }
}

interface NotificationsListProps {
    onClose?: () => void
}

export function NotificationsList({ onClose }: NotificationsListProps): JSX.Element {
    const { displayedNotifications, notificationsLoading, unreadCount, showUnreadOnly, hasMore } =
        useValues(notificationsLogic)
    const { markAllAsRead, setShowUnreadOnly, loadMoreNotifications } = useActions(notificationsLogic)

    return (
        <div className="flex flex-col h-full">
            <div className="flex items-center justify-between p-3 border-b">
                <div className="flex items-center gap-2">
                    <h3 className="m-0 text-base font-semibold">Notifications</h3>
                    <Tooltip title={showUnreadOnly ? 'Show all' : 'Show unread only'}>
                        <LemonSwitch checked={showUnreadOnly} onChange={setShowUnreadOnly} bordered />
                    </Tooltip>
                </div>
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
                {notificationsLoading && displayedNotifications.length === 0 ? (
                    <div className="flex items-center justify-center p-8">
                        <Spinner />
                    </div>
                ) : displayedNotifications.length === 0 ? (
                    <div className="flex flex-col items-center justify-center p-8 text-muted-alt">
                        <p className="text-center">No notifications yet</p>
                        <p className="text-xs text-center">When something important happens, you will see it here</p>
                    </div>
                ) : (
                    <>
                        <div className="divide-y">
                            {displayedNotifications.map((notification) => (
                                <NotificationItem key={notification.id} notification={notification} onClose={onClose} />
                            ))}
                        </div>
                        {hasMore && (
                            <div className="p-3 border-t">
                                <LemonButton
                                    fullWidth
                                    type="secondary"
                                    onClick={() => loadMoreNotifications()}
                                    loading={notificationsLoading}
                                >
                                    Load more
                                </LemonButton>
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    )
}

interface NotificationItemProps {
    notification: Notification
    onClose?: () => void
}

function NotificationItem({ notification, onClose }: NotificationItemProps): JSX.Element {
    const { toggleReadStatus, markAsRead } = useActions(notificationsLogic)
    const isUnread = !notification.read_at
    const timeAgo = dayjs(notification.created_at).fromNow()
    const notificationUrl = getNotificationUrl(notification)

    const handleLinkClick = (): void => {
        if (isUnread) {
            markAsRead(notification.id)
        }
        onClose?.()
    }

    return (
        <div
            className={clsx('p-3', {
                'bg-danger-highlight': isUnread,
            })}
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
                <div className="flex-shrink-0 flex gap-1">
                    {notificationUrl && (
                        <Tooltip title="Go to resource" placement="left">
                            <Link to={notificationUrl} onClick={handleLinkClick}>
                                <LemonButton size="xsmall" icon={<IconExternal />} type="secondary" noPadding />
                            </Link>
                        </Tooltip>
                    )}
                    <Tooltip title={isUnread ? 'Mark as read' : 'Mark as unread'} placement="left">
                        <LemonButton
                            size="xsmall"
                            icon={isUnread ? <IconRadioButtonUnchecked /> : <IconCheckCircle />}
                            onClick={(e) => {
                                e.stopPropagation()
                                toggleReadStatus(notification.id)
                            }}
                            type="secondary"
                            noPadding
                        />
                    </Tooltip>
                </div>
            </div>
        </div>
    )
}
