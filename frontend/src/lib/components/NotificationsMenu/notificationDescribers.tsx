import { WebAnalyticsDigestNotification } from 'lib/components/NotificationsMenu/WebAnalyticsDigestNotification'

import { InAppNotification } from '~/types'

export interface NotificationDescriberProps {
    notification: InAppNotification
    onNavigate?: () => void
}

export interface NotificationDescriber {
    takesOverRow?: boolean
    Component: (props: NotificationDescriberProps) => JSX.Element | null
}

function WebAnalyticsDigestDescriber({ notification }: NotificationDescriberProps): JSX.Element | null {
    if (!notification.metadata) {
        return null
    }

    return <WebAnalyticsDigestNotification metadata={notification.metadata} />
}

export const NOTIFICATION_DESCRIBERS: Record<string, NotificationDescriber> = {
    web_analytics_digest: { takesOverRow: true, Component: WebAnalyticsDigestDescriber },
}

export function getNotificationDescriber(notification: InAppNotification): NotificationDescriber | undefined {
    return NOTIFICATION_DESCRIBERS[notification.notification_type]
}
