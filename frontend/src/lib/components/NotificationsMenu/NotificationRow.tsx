import { useActions, useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { getNotificationDescriber } from 'lib/components/NotificationsMenu/notificationDescribers'
import { getNotificationIcon } from 'lib/components/NotificationsMenu/notificationToasts'
import { useAutoMarkRead } from 'lib/components/NotificationsMenu/useAutoMarkRead'
import { dayjs } from 'lib/dayjs'
import { IconOpenInNew, IconRadioButtonUnchecked } from 'lib/lemon-ui/icons'

import { sidePanelNotificationsLogic } from '~/layout/navigation/sidepanel/panels/activity/sidePanelNotificationsLogic'
import { InAppNotification } from '~/types'

export const REALTIME_NOTIFICATION_TYPE_META: Record<string, { label: string; description: string }> = {
    comment_mention: {
        label: 'Comment mentions',
        description: 'When someone @mentions you in a discussion',
    },
    alert_firing: {
        label: 'Alerts firing',
        description: 'When an alert you subscribe to triggers',
    },
    approval_requested: {
        label: 'Approvals requested',
        description: 'When a change is awaiting your approval',
    },
    approval_resolved: {
        label: 'Approvals resolved',
        description: 'When an approval you requested is decided',
    },
    pipeline_failure: {
        label: 'Pipeline failures',
        description: 'When a data pipeline or batch export fails',
    },
    issue_assigned: {
        label: 'Issues assigned',
        description: 'When an error tracking issue is assigned to you',
    },
    experiment_concluded: {
        label: 'Experiments concluded',
        description: 'When an experiment you created ends',
    },
    project_created: {
        label: 'Projects created',
        description: 'When a member creates a new project in your organization',
    },
    usage_spike: {
        label: 'Usage spikes',
        description: 'When billing detects a usage spike for one of your accounts',
    },
    reminder: {
        label: 'Reminders',
        description: 'When a reminder you scheduled is due',
    },
    web_analytics_digest: {
        label: 'Web analytics digest',
        description: 'Your weekly Web analytics summary is ready!',
    },
    achievement_unlocked: {
        label: 'Achievement unlocked',
        description: 'When you unlock a new achievement',
    },
}

export function NotificationTitle({
    notificationType,
    title,
}: {
    notificationType: string
    title: string
}): JSX.Element {
    // Float the icon so wrapped lines flow back under it (not a hanging indent),
    // break "Prefix: Name" titles at the colon
    const splitAt = title.indexOf(': ')
    return (
        <span className="block text-xs leading-snug font-semibold">
            {getNotificationIcon(notificationType, 'size-3.5 mt-px mr-1.5 float-left')}
            {splitAt === -1 ? (
                title
            ) : (
                <>
                    <span className="whitespace-nowrap">{title.slice(0, splitAt + 1)}</span>{' '}
                    <span className="whitespace-nowrap">{title.slice(splitAt + 2)}</span>
                </>
            )}
        </span>
    )
}

export function NotificationReadToggle({
    read,
    onToggle,
    target,
}: {
    read: boolean
    onToggle: (e: React.MouseEvent) => void
    target?: string
}): JSX.Element {
    return (
        <Tooltip title={`Mark ${target ? `${target} ` : ''}as ${read ? 'unread' : 'read'}`}>
            <button
                className="group/read shrink-0 flex size-5 items-center justify-center rounded hover:bg-fill-highlight-200 cursor-pointer"
                onClick={onToggle}
            >
                {read ? (
                    <IconCheckCircle className="size-4 text-success" />
                ) : (
                    <>
                        <IconRadioButtonUnchecked className="size-4 text-muted opacity-40 group-hover/read:hidden" />
                        <IconCheckCircle className="size-4 text-muted opacity-60 hidden group-hover/read:block" />
                    </>
                )}
            </button>
        </Tooltip>
    )
}

export function NotificationRow({
    notification,
    onNavigate,
}: {
    notification: InAppNotification
    onNavigate?: () => void
}): JSX.Element {
    const { navigateToNotification, toggleRead, markAsRead } = useActions(sidePanelNotificationsLogic)
    const { projectNameForNotification, sourcePathForNotification, manuallyToggledIds } =
        useValues(sidePanelNotificationsLogic)

    // Don't auto-mark a notification the user deliberately toggled this session — respect their intent.
    const autoMarkRef = useAutoMarkRead(!notification.read && !manuallyToggledIds.has(notification.id), () =>
        markAsRead(notification.id)
    )

    const otherProjectName = projectNameForNotification(notification)
    const describer = getNotificationDescriber(notification)
    const customBody = describer ? <describer.Component notification={notification} onNavigate={onNavigate} /> : null
    const rich = !!describer?.takesOverRow && !!notification.metadata

    const hasNavigationTarget = !!sourcePathForNotification(notification)
    const handleOpen = (): void => {
        // Clicking the card marks it read and navigates to its source
        if (!notification.read) {
            toggleRead(notification.id)
        }
        if (hasNavigationTarget) {
            navigateToNotification(notification)
            onNavigate?.()
        }
    }

    const handleToggleRead = (e: React.MouseEvent): void => {
        e.stopPropagation()
        toggleRead(notification.id)
    }

    const handleNavigate = (e: React.MouseEvent): void => {
        e.stopPropagation()
        handleOpen()
    }

    const resourceLabel = notification.resource_type
        ? `View ${notification.resource_type.replace(/_/g, ' ')}`
        : 'Go to source'

    return (
        <div
            ref={autoMarkRef}
            className={`group/row relative flex items-start gap-2 p-2 rounded cursor-pointer transition-colors ${
                notification.read ? 'hover:bg-fill-highlight-100' : 'bg-fill-highlight-50 hover:bg-fill-highlight-100'
            }`}
            onClick={handleOpen}
        >
            <div className="flex-1 min-w-0">
                <NotificationTitle
                    notificationType={notification.notification_type}
                    title={rich ? 'Web analytics digest' : notification.title}
                />
                {rich
                    ? customBody
                    : notification.body && (
                          <div className="text-xs text-secondary mt-2 text-pretty">{notification.body}</div>
                      )}
                <div className="flex items-center gap-1.5 mt-2">
                    <span className="text-[10px] text-muted">{dayjs(notification.created_at).fromNow()}</span>
                    {otherProjectName && (
                        <Tooltip title={`Notified on project ${otherProjectName}`}>
                            <span className="text-[10px] text-muted bg-fill-highlight-100 px-1 py-px rounded truncate max-w-[240px]">
                                {otherProjectName}
                            </span>
                        </Tooltip>
                    )}
                    {hasNavigationTarget && (
                        <button
                            onClick={handleNavigate}
                            className="inline-flex items-center gap-0.5 text-[10px] text-secondary opacity-0 transition-opacity hover:text-primary group-hover/row:opacity-100"
                        >
                            {resourceLabel}
                            <IconOpenInNew className="size-3" />
                        </button>
                    )}
                </div>
            </div>
            <div className="absolute bottom-1.5 right-1.5 opacity-0 transition-opacity group-hover/row:opacity-100">
                <NotificationReadToggle read={notification.read} onToggle={handleToggleRead} />
            </div>
        </div>
    )
}
