import { useActions } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconBug, IconCheckCircle, IconComment, IconNotification, IconPlug, IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { IconOpenInNew } from 'lib/lemon-ui/icons'

import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'
import { InAppNotification } from '~/types'

const NOTIFICATION_TYPE_ICONS: Record<string, JSX.Element> = {
    comment_mention: <IconComment className="size-5 text-primary" />,
    alert_firing: <IconWarning className="size-5 text-warning" />,
    approval_requested: <IconCheckCircle className="size-5 text-success" />,
    approval_resolved: <IconCheckCircle className="size-5 text-success" />,
    pipeline_failure: <IconPlug className="size-5 text-danger" />,
    issue_assigned: <IconBug className="size-5 text-primary" />,
}

function getNotificationIcon(notificationType: string): JSX.Element {
    return NOTIFICATION_TYPE_ICONS[notificationType] ?? <IconNotification className="size-5 text-secondary" />
}

export function NotificationRow({
    notification,
    onNavigate,
}: {
    notification: InAppNotification
    onNavigate?: () => void
}): JSX.Element {
    const { markAsRead, toggleRead } = useActions(sidePanelNotificationsLogic)
    const [expanded, setExpanded] = useState(false)

    const handleNavigate = (e: React.MouseEvent): void => {
        e.stopPropagation()
        if (!notification.read) {
            markAsRead(notification.id)
        }
        if (notification.source_url) {
            router.actions.push(notification.source_url)
            onNavigate?.()
        }
    }

    const handleToggleRead = (e: React.MouseEvent): void => {
        e.stopPropagation()
        toggleRead(notification.id)
    }

    return (
        <div
            className={`flex items-start gap-2.5 p-2 rounded cursor-pointer transition-colors ${
                notification.read ? 'hover:bg-fill-highlight-100' : 'bg-fill-highlight-50 hover:bg-fill-highlight-100'
            }`}
            onClick={() => notification.body && setExpanded(!expanded)}
        >
            <div className="shrink-0 mt-0.5">{getNotificationIcon(notification.notification_type)}</div>
            <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-1">
                    <span className={`text-xs leading-snug ${notification.read ? 'text-secondary' : 'font-semibold'}`}>
                        {notification.title}
                    </span>
                    <div className="flex items-center gap-1 shrink-0">
                        {notification.source_url && (
                            <Tooltip title="Go to source">
                                <button
                                    className="p-0.5 rounded hover:bg-fill-highlight-200 text-secondary hover:text-primary cursor-pointer"
                                    onClick={handleNavigate}
                                >
                                    <IconOpenInNew className="size-3.5" />
                                </button>
                            </Tooltip>
                        )}
                        <Tooltip title={notification.read ? 'Mark as unread' : 'Mark as read'}>
                            <button
                                className="p-0.5 rounded hover:bg-fill-highlight-200 cursor-pointer"
                                onClick={handleToggleRead}
                            >
                                <div
                                    className={`size-2.5 rounded-full border ${
                                        notification.read
                                            ? 'border-secondary bg-transparent'
                                            : 'border-danger bg-danger'
                                    }`}
                                />
                            </button>
                        </Tooltip>
                    </div>
                </div>
                {notification.body && (
                    <div className={`text-xs text-secondary mt-0.5 ${expanded ? '' : 'line-clamp-1'}`}>
                        {notification.body}
                    </div>
                )}
                <div className="text-[10px] text-muted mt-0.5">{dayjs(notification.created_at).fromNow()}</div>
            </div>
        </div>
    )
}
