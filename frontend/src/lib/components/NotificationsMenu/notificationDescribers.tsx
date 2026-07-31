import { AchievementUnlockedNotification } from 'lib/components/NotificationsMenu/AchievementUnlockedNotification'
import { WebAnalyticsDigestNotification } from 'lib/components/NotificationsMenu/WebAnalyticsDigestNotification'

import {
    InAppNotification,
    InAppNotificationMetadata,
    WebAnalyticsAchievementMetadata,
    WebAnalyticsDigestMetadata,
} from '~/types'

export interface NotificationDescriberProps {
    notification: InAppNotification
    onNavigate?: () => void
}

export interface NotificationDescriber {
    /**
     * Whether this payload can render the rich card, which then replaces the row's title and body.
     * Returning false keeps the plain fallback, so an unexpected payload never leaves an empty card.
     */
    takesOverRow?: (notification: InAppNotification) => boolean
    /** Replaces the notification's own title when the describer takes over the row */
    title?: string
    /** Label for the row's primary action, which stays visible instead of appearing on hover */
    actionLabel?: string
    Component: (props: NotificationDescriberProps) => JSX.Element | null
}

function isDigestMetadata(metadata: InAppNotificationMetadata | null): metadata is WebAnalyticsDigestMetadata {
    return !!metadata && Array.isArray((metadata as WebAnalyticsDigestMetadata).metrics)
}

function isAchievementMetadata(
    metadata: InAppNotificationMetadata | null
): metadata is WebAnalyticsAchievementMetadata {
    const achievement = metadata as WebAnalyticsAchievementMetadata | null
    return (
        !!achievement &&
        typeof achievement.track_name === 'string' &&
        typeof achievement.stage_name === 'string' &&
        typeof achievement.stage === 'number'
    )
}

function WebAnalyticsDigestDescriber({ notification }: NotificationDescriberProps): JSX.Element | null {
    if (!isDigestMetadata(notification.metadata)) {
        return null
    }

    return <WebAnalyticsDigestNotification metadata={notification.metadata} />
}

function AchievementUnlockedDescriber({ notification }: NotificationDescriberProps): JSX.Element | null {
    if (!isAchievementMetadata(notification.metadata)) {
        return null
    }

    return <AchievementUnlockedNotification metadata={notification.metadata} />
}

export const NOTIFICATION_DESCRIBERS: Record<string, NotificationDescriber> = {
    web_analytics_digest: {
        takesOverRow: (notification) => isDigestMetadata(notification.metadata),
        title: 'Web analytics digest',
        Component: WebAnalyticsDigestDescriber,
    },
    achievement_unlocked: {
        takesOverRow: (notification) => isAchievementMetadata(notification.metadata),
        title: 'Achievement unlocked',
        actionLabel: 'View achievements',
        Component: AchievementUnlockedDescriber,
    },
}

export function getNotificationDescriber(notification: InAppNotification): NotificationDescriber | undefined {
    return NOTIFICATION_DESCRIBERS[notification.notification_type]
}
