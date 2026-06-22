import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArchive } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import {
    NotificationActionButton,
    ReadToggleIcon,
    ROW_ACTION_REVEAL_CLASSES,
} from 'lib/components/NotificationsMenu/NotificationActionButton'
import { getNotificationDescriber } from 'lib/components/NotificationsMenu/notificationDescribers'
import { getNotificationIcon } from 'lib/components/NotificationsMenu/notificationToasts'
import { dayjs } from 'lib/dayjs'
import { IconOpenInNew } from 'lib/lemon-ui/icons'

import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'
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

export function NotificationRow({
    notification,
    onNavigate,
    readOnly = false,
}: {
    notification: InAppNotification
    onNavigate?: () => void
    readOnly?: boolean
}): JSX.Element {
    const { navigateToNotification, toggleRead, archiveNotification } = useActions(sidePanelNotificationsLogic)
    const { projectNameForNotification, sourcePathForNotification } = useValues(sidePanelNotificationsLogic)
    const [expanded, setExpanded] = useState(false)

    const otherProjectName = projectNameForNotification(notification)
    const describer = getNotificationDescriber(notification)
    const customBody = describer ? <describer.Component notification={notification} onNavigate={onNavigate} /> : null
    const rich = !!describer?.takesOverRow && !!notification.metadata

    const hasNavigationTarget = !!sourcePathForNotification(notification)
    const handleNavigate = (e: React.MouseEvent): void => {
        e.stopPropagation()
        if (hasNavigationTarget) {
            navigateToNotification(notification)
            onNavigate?.()
        }
    }

    const handleToggleRead = (e: React.MouseEvent): void => {
        e.stopPropagation()
        toggleRead(notification.id)
    }

    const handleArchive = (e: React.MouseEvent): void => {
        e.stopPropagation()
        archiveNotification(notification.id)
    }

    return (
        <div
            className={`group/row flex items-start gap-2.5 p-2 rounded transition-colors ${
                rich ? '' : 'cursor-pointer'
            } ${
                notification.read ? 'hover:bg-fill-highlight-100' : 'bg-fill-highlight-50 hover:bg-fill-highlight-100'
            }`}
            onClick={rich ? undefined : () => notification.body && setExpanded(!expanded)}
        >
            <div className="shrink-0 mt-0.5">{getNotificationIcon(notification.notification_type)}</div>
            <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-1">
                    {rich ? (
                        <span className="text-[10px] font-semibold uppercase tracking-wide text-muted mt-1">
                            Web analytics digest
                        </span>
                    ) : (
                        <span
                            className={`text-xs leading-snug ${notification.read ? 'text-secondary' : 'font-semibold'}`}
                        >
                            {notification.title}
                        </span>
                    )}
                    <div className="flex items-center gap-1 shrink-0">
                        {!rich && hasNavigationTarget && (
                            <NotificationActionButton
                                icon={<IconOpenInNew className="size-4" />}
                                tooltip="Go to source"
                                onClick={handleNavigate}
                                className={ROW_ACTION_REVEAL_CLASSES}
                            />
                        )}
                        {!readOnly && (
                            <NotificationActionButton
                                className="group/read"
                                tooltip={notification.read ? 'Mark as unread' : 'Mark as read'}
                                onClick={handleToggleRead}
                                icon={<ReadToggleIcon read={notification.read} />}
                            />
                        )}
                        {!readOnly && (
                            <div className="ml-1 min-w-[26px] min-h-[26px] flex">
                                {notification.archivable && (
                                    <NotificationActionButton
                                        icon={<IconArchive className="size-4" />}
                                        tooltip="Archive"
                                        onClick={handleArchive}
                                        tone="danger"
                                    />
                                )}
                            </div>
                        )}
                    </div>
                </div>
                {rich
                    ? customBody
                    : notification.body && (
                          <div className={`text-xs text-secondary mt-0.5 ${expanded ? '' : 'line-clamp-1'}`}>
                              {notification.body}
                          </div>
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
                </div>
            </div>
        </div>
    )
}
