import { INSIGHT_ALERT_FIRING_EVENT_ID, INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID } from 'lib/constants'
import {
    HOG_FUNCTION_SUB_TEMPLATES,
    HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES,
} from 'scenes/hog-functions/sub-templates/sub-templates'

import { CyclotronJobFiltersType, HogFunctionType, PropertyFilterType, PropertyOperator } from '~/types'

export const ALERT_NOTIFICATION_TYPE_SLACK = 'slack' as const
export const ALERT_NOTIFICATION_TYPE_WEBHOOK = 'webhook' as const
export type AlertNotificationType = typeof ALERT_NOTIFICATION_TYPE_SLACK | typeof ALERT_NOTIFICATION_TYPE_WEBHOOK

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

const INSIGHT_ALERT_SLACK_INPUTS =
    HOG_FUNCTION_SUB_TEMPLATES[INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID].find((t) => t.template_id === 'template-slack')
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

export function buildHogFunctionPayload(
    alertId: string,
    alertName: string | undefined,
    notification: PendingAlertNotification
): Partial<HogFunctionType> {
    const commonProps = HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID]
    const base = {
        type: commonProps.type,
        enabled: true,
        masking: null,
        filters: buildAlertFilterConfig(alertId),
    }

    if (notification.type === 'slack') {
        return {
            ...base,
            name: `${alertName ?? 'Alert'}: Slack #${notification.slackChannelName ?? 'channel'}`,
            template_id: 'template-slack',
            inputs: {
                ...INSIGHT_ALERT_SLACK_INPUTS,
                slack_workspace: { value: notification.slackWorkspaceId },
                channel: { value: notification.slackChannelId },
            },
        }
    }

    return {
        ...base,
        name: `${alertName ?? 'Alert'}: Webhook ${notification.webhookUrl}`,
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
}
