import { INSIGHT_ALERT_FIRING_EVENT_ID, INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID } from 'lib/constants'
import {
    HOG_FUNCTION_SUB_TEMPLATES,
    HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES,
} from 'scenes/hog-functions/sub-templates/sub-templates'

import { CyclotronJobFiltersType, HogFunctionType, PropertyFilterType, PropertyOperator } from '~/types'

export const ALERT_NOTIFICATION_TYPE_SLACK = 'slack' as const
export const ALERT_NOTIFICATION_TYPE_WEBHOOK = 'webhook' as const
export const ALERT_NOTIFICATION_TYPE_DISCORD = 'discord' as const
export const ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS = 'microsoft_teams' as const
export type AlertNotificationType =
    | typeof ALERT_NOTIFICATION_TYPE_SLACK
    | typeof ALERT_NOTIFICATION_TYPE_WEBHOOK
    | typeof ALERT_NOTIFICATION_TYPE_DISCORD
    | typeof ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS

export const buildAlertFilterConfig = (alertId: string): CyclotronJobFiltersType => ({
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
            id: INSIGHT_ALERT_FIRING_EVENT_ID,
            type: 'events',
        },
    ],
})

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

export function buildHogFunctionPayload(
    alertId: string,
    alertName: string | undefined,
    notification: PendingAlertNotification
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
    notification: PendingAlertNotification
): Pick<HogFunctionType, 'name' | 'template_id' | 'inputs'> {
    switch (notification.type) {
        case ALERT_NOTIFICATION_TYPE_SLACK:
            return {
                name: `${alertName}: Slack #${notification.slackChannelName ?? 'channel'}`,
                template_id: 'template-slack',
                inputs: {
                    ...subTemplateInputs('template-slack'),
                    slack_workspace: { value: notification.slackWorkspaceId },
                    channel: { value: notification.slackChannelId },
                },
            }
        case ALERT_NOTIFICATION_TYPE_DISCORD:
            return {
                name: `${alertName}: Discord`,
                template_id: 'template-discord',
                inputs: {
                    ...subTemplateInputs('template-discord'),
                    webhookUrl: { value: notification.webhookUrl },
                },
            }
        case ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS:
            return {
                name: `${alertName}: Microsoft Teams`,
                template_id: 'template-microsoft-teams',
                inputs: {
                    ...subTemplateInputs('template-microsoft-teams'),
                    webhookUrl: { value: notification.webhookUrl },
                },
            }
        case ALERT_NOTIFICATION_TYPE_WEBHOOK:
            return {
                name: `${alertName}: Webhook ${notification.webhookUrl}`,
                template_id: 'template-webhook',
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
