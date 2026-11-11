import { z } from 'zod'

import {
    INSIGHT_ALERT_FIRING_EVENT_ID,
    INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID,
    INSIGHT_ALERT_INCIDENT_CLOSED_EVENT_ID,
    INSIGHT_ALERT_INCIDENT_OPENED_EVENT_ID,
} from 'lib/constants'
import {
    HOG_FUNCTION_SUB_TEMPLATES,
    HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES,
} from 'scenes/hog-functions/sub-templates/sub-templates'

import { CyclotronJobFiltersType, HogFunctionType, PropertyFilterType, PropertyOperator } from '~/types'

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

// Single source of truth for which destination HogFunction template each notification type uses.
// buildAlertDestination reads it when creating a destination; notificationTypeFromTemplateId inverts
// it to label an existing one. Keeping both directions off one map avoids the two drifting apart.
const TEMPLATE_ID_BY_NOTIFICATION_TYPE: Record<AlertNotificationType, string> = {
    [ALERT_NOTIFICATION_TYPE_SLACK]: 'template-slack',
    [ALERT_NOTIFICATION_TYPE_DISCORD]: 'template-discord',
    [ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS]: 'template-microsoft-teams',
    [ALERT_NOTIFICATION_TYPE_WEBHOOK]: 'template-webhook',
    [ALERT_NOTIFICATION_TYPE_PAGERDUTY]: 'template-pagerduty',
}

// Maps a destination HogFunction's template_id back to the notification type, so analytics and
// UI code can label an existing destination without re-deriving it from inputs.
export const notificationTypeFromTemplateId = (templateId?: string | null): AlertNotificationType | null => {
    const match = Object.entries(TEMPLATE_ID_BY_NOTIFICATION_TYPE).find(([, id]) => id === templateId)
    return match ? (match[0] as AlertNotificationType) : null
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

export const listensOnEvent = (hogFunction: Pick<HogFunctionType, 'filters'>, eventId: string): boolean =>
    hogFunction.filters?.events?.some((event) => event.id === eventId) ?? false

// The opened event alone stands for a PagerDuty destination, so a count sees it once.
export const buildAlertDestinationCountFilterGroups = (alertId: string): CyclotronJobFiltersType[] => [
    buildAlertFilterConfig(alertId),
    buildAlertFilterConfig(alertId, INSIGHT_ALERT_INCIDENT_OPENED_EVENT_ID),
]

export const buildAlertDestinationFilterGroups = (alertId: string): CyclotronJobFiltersType[] =>
    [INSIGHT_ALERT_FIRING_EVENT_ID, INSIGHT_ALERT_INCIDENT_OPENED_EVENT_ID, INSIGHT_ALERT_INCIDENT_CLOSED_EVENT_ID].map(
        (eventId) => buildAlertFilterConfig(alertId, eventId)
    )

// A webhook URL's path and query are the channel credential for every webhook-style provider, and a
// destination name reaches surfaces its configuration does not, such as the subject line of the email
// sent when the destination is disabled. The host is all a name needs to tell two destinations apart.
const webhookUrlHost = (url: string): string => {
    try {
        return new URL(url).hostname || 'destination'
    } catch {
        return 'destination'
    }
}

// Default inputs the alert wizard pre-fills for a destination, sourced from the shared sub-template
// (single source of truth with the full destination picker).
const subTemplateInputs = (templateId: string): NonNullable<HogFunctionType['inputs']> =>
    HOG_FUNCTION_SUB_TEMPLATES[INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID].find((t) => t.template_id === templateId)
        ?.inputs ?? {}

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

// The alert API builds a PagerDuty destination, because the HogFunction API refuses the incident events.
export type HogFunctionAlertNotification = Exclude<
    PendingAlertNotification,
    { type: typeof ALERT_NOTIFICATION_TYPE_PAGERDUTY }
>

export function buildHogFunctionPayload(
    alertId: string,
    alertName: string | undefined,
    notification: HogFunctionAlertNotification
): Partial<HogFunctionType> {
    const commonProps = HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID]
    return {
        type: commonProps.type,
        enabled: true,
        masking: null,
        filters: buildAlertFilterConfig(alertId),
        ...buildAlertDestination(alertName ?? 'Alert', notification),
    }
}

// Per-destination name, template, and inputs. One exhaustive case per notification type — adding a
// destination is a single case here plus an entry in PendingAlertNotification and the dropdown options.
function buildAlertDestination(
    alertName: string,
    notification: HogFunctionAlertNotification
): Pick<HogFunctionType, 'name' | 'template_id' | 'inputs'> {
    switch (notification.type) {
        case ALERT_NOTIFICATION_TYPE_SLACK:
            return {
                name: `${alertName}: Slack #${notification.slackChannelName ?? 'channel'}`,
                template_id: TEMPLATE_ID_BY_NOTIFICATION_TYPE[ALERT_NOTIFICATION_TYPE_SLACK],
                inputs: {
                    ...subTemplateInputs(TEMPLATE_ID_BY_NOTIFICATION_TYPE[ALERT_NOTIFICATION_TYPE_SLACK]),
                    slack_workspace: { value: notification.slackWorkspaceId },
                    channel: { value: notification.slackChannelId },
                },
            }
        case ALERT_NOTIFICATION_TYPE_DISCORD:
            return {
                name: `${alertName}: Discord`,
                template_id: TEMPLATE_ID_BY_NOTIFICATION_TYPE[ALERT_NOTIFICATION_TYPE_DISCORD],
                inputs: {
                    ...subTemplateInputs(TEMPLATE_ID_BY_NOTIFICATION_TYPE[ALERT_NOTIFICATION_TYPE_DISCORD]),
                    webhookUrl: { value: notification.webhookUrl },
                },
            }
        case ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS:
            return {
                name: `${alertName}: Microsoft Teams`,
                template_id: TEMPLATE_ID_BY_NOTIFICATION_TYPE[ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS],
                inputs: {
                    ...subTemplateInputs(TEMPLATE_ID_BY_NOTIFICATION_TYPE[ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS]),
                    webhookUrl: { value: notification.webhookUrl },
                },
            }
        case ALERT_NOTIFICATION_TYPE_WEBHOOK:
            return {
                name: `${alertName}: Webhook ${webhookUrlHost(notification.webhookUrl)}`,
                template_id: TEMPLATE_ID_BY_NOTIFICATION_TYPE[ALERT_NOTIFICATION_TYPE_WEBHOOK],
                inputs: {
                    url: { value: notification.webhookUrl },
                    body: {
                        value: {
                            alert_name: '{event.properties.alert_name}',
                            insight_name: '{event.properties.insight_name}',
                            breaches: '{event.properties.breaches}',
                            insight_url: '{project.url}/insights/{event.properties.insight_id}',
                            alert_url:
                                '{project.url}/insights/{event.properties.insight_id}/alerts?alert_id={event.properties.alert_id}',
                        },
                    },
                },
            }
        default:
            // Compile error if a PendingAlertNotification variant is added without a case above.
            notification satisfies never
            throw new Error('Unhandled alert notification type')
    }
}
