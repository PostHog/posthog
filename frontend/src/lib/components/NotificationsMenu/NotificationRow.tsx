import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheckCircle } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { getNotificationIcon } from 'lib/components/NotificationsMenu/notificationToasts'
import { dayjs } from 'lib/dayjs'
import { IconRadioButtonUnchecked } from 'lib/lemon-ui/icons'
import { IconOpenInNew } from 'lib/lemon-ui/icons'

import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'
import { InAppNotification } from '~/types'

export function NotificationRow({
    notification,
    onNavigate,
}: {
    notification: InAppNotification
    onNavigate?: () => void
}): JSX.Element {
    const { navigateToNotification, toggleRead } = useActions(sidePanelNotificationsLogic)
    const { projectNameForNotification, sourcePathForNotification } = useValues(sidePanelNotificationsLogic)
    const [expanded, setExpanded] = useState(false)

    const otherProjectName = projectNameForNotification(notification)

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
                        {hasNavigationTarget && (
                            <Tooltip title="Go to source">
                                <button
                                    className="min-w-[26px] min-h-[26px] flex items-center justify-center rounded hover:bg-fill-highlight-200 text-secondary hover:text-primary cursor-pointer"
                                    onClick={handleNavigate}
                                >
                                    <IconOpenInNew className="size-4" />
                                </button>
                            </Tooltip>
                        )}
                        <Tooltip title={notification.read ? 'Mark as unread' : 'Mark as read'}>
                            <button
                                className="group/read min-w-[26px] min-h-[26px] flex items-center justify-center rounded hover:bg-fill-highlight-200 cursor-pointer"
                                onClick={handleToggleRead}
                            >
                                {notification.read ? (
                                    <IconCheckCircle className="size-4 text-success" />
                                ) : (
                                    <>
                                        <IconRadioButtonUnchecked className="size-4 text-muted opacity-40 group-hover/read:hidden" />
                                        <IconCheckCircle className="size-4 text-muted opacity-60 hidden group-hover/read:block" />
                                    </>
                                )}
                            </button>
                        </Tooltip>
                    </div>
                </div>
                {notification.body && (
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
