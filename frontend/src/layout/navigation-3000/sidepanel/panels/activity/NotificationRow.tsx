import { useActions } from 'kea'
import { router } from 'kea-router'

import { dayjs } from 'lib/dayjs'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { InAppNotification } from '~/types'

import { sidePanelStateLogic } from '../../sidePanelStateLogic'
import { sidePanelNotificationsLogic } from './sidePanelNotificationsLogic'

export function NotificationRow({ notification }: { notification: InAppNotification }): JSX.Element {
    const { markAsRead } = useActions(sidePanelNotificationsLogic)
    const { closeSidePanel } = useActions(sidePanelStateLogic)

    const handleClick = (): void => {
        if (!notification.read) {
            markAsRead(notification.id)
        }
        if (notification.source_url) {
            closeSidePanel()
            router.actions.push(notification.source_url)
        }
    }

    return (
        <div
            className={`flex items-start gap-3 p-2 rounded cursor-pointer hover:bg-fill-highlight-100 ${
                notification.read ? '' : 'bg-fill-highlight-50'
            }`}
            onClick={handleClick}
        >
            <div className="shrink-0 mt-0.5">
                {notification.actor ? (
                    <ProfilePicture user={notification.actor} size="md" />
                ) : (
                    <ProfilePicture user={{ first_name: 'PostHog' }} size="md" />
                )}
            </div>
            <div className="flex-1 min-w-0">
                <div className="flex items-start gap-2">
                    <span className={`text-sm leading-snug ${notification.read ? '' : 'font-semibold'}`}>
                        {notification.title}
                    </span>
                    {!notification.read && <div className="shrink-0 w-2 h-2 rounded-full bg-primary mt-1.5" />}
                </div>
                {notification.body && <div className="text-xs text-secondary mt-0.5 truncate">{notification.body}</div>}
                <div className="text-xs text-muted mt-0.5">{dayjs(notification.created_at).fromNow()}</div>
            </div>
        </div>
    )
}
