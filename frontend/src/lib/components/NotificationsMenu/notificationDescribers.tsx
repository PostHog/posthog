import { useActions } from 'kea'

import { WebAnalyticsDigestNotification } from 'lib/components/NotificationsMenu/WebAnalyticsDigestNotification'

import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'
import { InAppNotification } from '~/types'

export interface NotificationDescriberProps {
    notification: InAppNotification
    onNavigate?: () => void
}

export interface NotificationDescriber {
    takesOverRow?: boolean
    Component: (props: NotificationDescriberProps) => JSX.Element | null
}

function WebAnalyticsDigestDescriber({ notification, onNavigate }: NotificationDescriberProps): JSX.Element | null {
    const { viewWebAnalyticsFromDigest, askMaxAboutDigest } = useActions(sidePanelNotificationsLogic)

    if (!notification.metadata) {
        return null
    }

    return (
        <WebAnalyticsDigestNotification
            metadata={notification.metadata}
            onOpen={(e) => {
                e.stopPropagation()
                viewWebAnalyticsFromDigest(notification)
                onNavigate?.()
            }}
            onAskMax={(e) => {
                e.stopPropagation()
                askMaxAboutDigest(notification)
                onNavigate?.()
            }}
        />
    )
}

export const NOTIFICATION_DESCRIBERS: Record<string, NotificationDescriber> = {
    web_analytics_digest: { takesOverRow: true, Component: WebAnalyticsDigestDescriber },
}

export function getNotificationDescriber(notification: InAppNotification): NotificationDescriber | undefined {
    return NOTIFICATION_DESCRIBERS[notification.notification_type]
}
