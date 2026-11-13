import { z } from 'zod'

import { INSIGHT_ALERT_FIRING_EVENT_ID, INSIGHT_ALERT_INCIDENT_OPENED_EVENT_ID } from 'lib/constants'

import { CyclotronJobFiltersType, PropertyFilterType, PropertyOperator } from '~/types'

import {
    type AlertPagerDutyRegion,
    type AlertPagerDutySeverity,
    pagerDutyRoutingKeyError,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'

export const ALERT_NOTIFICATION_TYPE_SLACK = 'slack' as const
export const ALERT_NOTIFICATION_TYPE_WEBHOOK = 'webhook' as const
export const ALERT_NOTIFICATION_TYPE_DISCORD = 'discord' as const
export const ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS = 'microsoft_teams' as const
export const ALERT_NOTIFICATION_TYPE_PAGERDUTY = 'pagerduty' as const
export type AlertNotificationType =
    | typeof ALERT_NOTIFICATION_TYPE_SLACK
    | typeof ALERT_NOTIFICATION_TYPE_WEBHOOK
    | typeof ALERT_NOTIFICATION_TYPE_DISCORD
    | typeof ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS
    | typeof ALERT_NOTIFICATION_TYPE_PAGERDUTY

const webhookUrlSchema = z.string().url()

export function getAlertNotificationAddDisabledReason(
    selectedType: AlertNotificationType,
    hasSlackIntegration: boolean,
    slackChannelValue: string | null,
    webhookUrl: string,
    pagerDutyRoutingKey: string
): string | undefined {
    if (selectedType === ALERT_NOTIFICATION_TYPE_PAGERDUTY) {
        return pagerDutyRoutingKeyError(pagerDutyRoutingKey)
    }

    if (selectedType === ALERT_NOTIFICATION_TYPE_SLACK) {
        if (!hasSlackIntegration) {
            return 'Connect Slack first'
        }
        if (!slackChannelValue) {
            return 'Select a Slack channel'
        }
        return undefined
    }

    if (!webhookUrl) {
        if (selectedType === ALERT_NOTIFICATION_TYPE_DISCORD) {
            return 'Enter a Discord webhook URL'
        }
        if (selectedType === ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS) {
            return 'Enter a Microsoft Teams workflow URL'
        }
        return 'Enter a webhook URL'
    }

    if (!webhookUrlSchema.safeParse(webhookUrl).success) {
        if (selectedType === ALERT_NOTIFICATION_TYPE_DISCORD) {
            return 'Enter a valid Discord webhook URL'
        }
        if (selectedType === ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS) {
            return 'Enter a valid Microsoft Teams workflow URL'
        }
        return 'Enter a valid webhook URL'
    }

    return undefined
}

export const buildAlertFilterConfig = (
    alertId: string,
    eventId: string = INSIGHT_ALERT_FIRING_EVENT_ID
): CyclotronJobFiltersType => ({
    properties: [
        {
            key: 'alert_id',
            value: alertId,
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        },
    ],
    events: [
        {
            id: eventId,
            type: 'events',
        },
    ],
})

// The opened event alone stands for a PagerDuty destination, so a count sees it once.
export const buildAlertDestinationCountFilterGroups = (alertId: string): CyclotronJobFiltersType[] => [
    buildAlertFilterConfig(alertId),
    buildAlertFilterConfig(alertId, INSIGHT_ALERT_INCIDENT_OPENED_EVENT_ID),
]

export type PendingAlertNotification =
    | {
          type: typeof ALERT_NOTIFICATION_TYPE_SLACK
          slackWorkspaceId: number
          slackChannelId: string
          slackChannelName?: string
      }
    | {
          type: typeof ALERT_NOTIFICATION_TYPE_WEBHOOK
          webhookUrl: string
      }
    | {
          type: typeof ALERT_NOTIFICATION_TYPE_DISCORD
          webhookUrl: string
      }
    | {
          type: typeof ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS
          webhookUrl: string
      }
    | {
          type: typeof ALERT_NOTIFICATION_TYPE_PAGERDUTY
          routingKey: string
          severity: AlertPagerDutySeverity
          region: AlertPagerDutyRegion
      }
