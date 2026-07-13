import { ComponentType } from 'react'

import {
    IconBug,
    IconCheckCircle,
    IconClock,
    IconComment,
    IconFlask,
    IconFolder,
    IconNotification,
    IconPieChart,
    IconPlug,
    IconStar,
    IconTrending,
    IconWarning,
} from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'

import { notificationsMenuLogic } from 'lib/components/NotificationsMenu/notificationsMenuLogic'

import { InAppNotification } from '~/types'

const NOTIFICATION_TYPE_ICONS: Record<string, { Icon: ComponentType<{ className?: string }>; color: string }> = {
    comment_mention: { Icon: IconComment, color: 'text-primary' },
    alert_firing: { Icon: IconWarning, color: 'text-warning' },
    approval_requested: { Icon: IconCheckCircle, color: 'text-success' },
    approval_resolved: { Icon: IconCheckCircle, color: 'text-success' },
    pipeline_failure: { Icon: IconPlug, color: 'text-danger' },
    issue_assigned: { Icon: IconBug, color: 'text-primary' },
    experiment_concluded: { Icon: IconFlask, color: 'text-primary' },
    project_created: { Icon: IconFolder, color: 'text-primary' },
    usage_spike: { Icon: IconTrending, color: 'text-warning' },
    reminder: { Icon: IconClock, color: 'text-primary' },
    web_analytics_digest: { Icon: IconPieChart, color: 'text-primary' },
    achievement_unlocked: { Icon: IconStar, color: 'text-warning' },
}

export function getNotificationIcon(notificationType: string, className: string = 'size-5'): JSX.Element {
    const { Icon, color } = NOTIFICATION_TYPE_ICONS[notificationType] ?? {
        Icon: IconNotification,
        color: 'text-secondary',
    }
    return <Icon className={`${className} ${color} shrink-0`} />
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
