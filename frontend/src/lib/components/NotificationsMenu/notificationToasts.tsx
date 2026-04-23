import { IconBug, IconCheckCircle, IconComment, IconNotification, IconPlug, IconWarning } from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'

import { notificationsMenuLogic } from 'lib/components/NotificationsMenu/notificationsMenuLogic'

import { InAppNotification } from '~/types'

const NOTIFICATION_TYPE_ICONS: Record<string, JSX.Element> = {
    comment_mention: <IconComment className="size-5 text-primary shrink-0" />,
    alert_firing: <IconWarning className="size-5 text-warning shrink-0" />,
    approval_requested: <IconCheckCircle className="size-5 text-success shrink-0" />,
    approval_resolved: <IconCheckCircle className="size-5 text-success shrink-0" />,
    pipeline_failure: <IconPlug className="size-5 text-danger shrink-0" />,
    issue_assigned: <IconBug className="size-5 text-primary shrink-0" />,
}

export function getNotificationIcon(notificationType: string): JSX.Element {
    return NOTIFICATION_TYPE_ICONS[notificationType] ?? <IconNotification className="size-5 text-secondary shrink-0" />
}

export function showCriticalNotificationToast(notification: InAppNotification): void {
    const icon = getNotificationIcon(notification.notification_type)
    lemonToast.info(
        <div className="flex items-start gap-2">
            {icon}
            <div className="min-w-0">
                <div className="font-semibold text-xs">{notification.title}</div>
                {notification.body && (
                    <div className="text-xs text-secondary mt-0.5 line-clamp-1">{notification.body}</div>
                )}
            </div>
        </div>,
        {
            icon: false,
            autoClose: false,
            toastId: `notification-${notification.id}`,
            button: {
                label: 'Open notifications',
                action: () => notificationsMenuLogic.actions.openToUnread(),
            },
        }
    )
}
