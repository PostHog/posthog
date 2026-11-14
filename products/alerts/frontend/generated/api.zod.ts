/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const AlertsCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const AlertsUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const AlertsPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Send this alert to a Slack channel as well as by email. The workspace must already be connected to the project. The returned IDs identify the destination.
 */
export const alertsDestinationsCreateBodyTypeDefault = `slack`

export const AlertsDestinationsCreateBody = /* @__PURE__ */ zod.object({
    type: zod
        .enum(['slack'])
        .describe('\* `slack` - slack')
        .default(alertsDestinationsCreateBodyTypeDefault)
        .describe('Destination type. Slack is the only type this endpoint creates.\n\n\* `slack` - slack'),
    slack_workspace_id: zod
        .number()
        .describe('Integration ID of the Slack workspace to post in. List them with the integrations endpoint.'),
    slack_channel_id: zod.string().describe('Slack channel ID to post in, for example C0123456789.'),
    slack_channel_name: zod
        .string()
        .optional()
        .describe('Channel name shown on the destination, for example product-alerts.'),
})

/**
 * Stop sending this alert to a destination. The alert keeps its email recipients.
 */
export const alertsDestinationsDeleteCreateBodyHogFunctionIdsMax = 100

export const alertsDestinationsDeleteCreateBodyDestinationIdsMax = 100

export const AlertsDestinationsDeleteCreateBody = /* @__PURE__ */ zod.object({
    hog_function_ids: zod
        .array(zod.uuid())
        .max(alertsDestinationsDeleteCreateBodyHogFunctionIdsMax)
        .optional()
        .describe('HogFunction IDs of the destination, as returned when it was created.'),
    destination_ids: zod
        .array(zod.uuid())
        .max(alertsDestinationsDeleteCreateBodyDestinationIdsMax)
        .optional()
        .describe('Destination IDs from the destinations list, to delete with their HogFunctions.'),
})

/**
 * Open a PagerDuty incident when this alert starts firing, and resolve it when the alert stops. Only an alert whose pagerduty_available is true can take one. The returned IDs identify the destination.
 */
export const alertsDestinationsPagerdutyCreateBodyPagerdutySeverityDefault = `critical`
export const alertsDestinationsPagerdutyCreateBodyPagerdutyRegionDefault = `us`

export const AlertsDestinationsPagerdutyCreateBody = /* @__PURE__ */ zod.object({
    pagerduty_routing_key: zod
        .string()
        .describe('The 32-character integration key of a PagerDuty Events API v2 integration.'),
    pagerduty_severity: zod
        .enum(['critical', 'error', 'warning', 'info'])
        .describe('\* `critical` - critical\n\* `error` - error\n\* `warning` - warning\n\* `info` - info')
        .default(alertsDestinationsPagerdutyCreateBodyPagerdutySeverityDefault)
        .describe(
            'Severity of the incidents the alert opens.\n\n\* `critical` - critical\n\* `error` - error\n\* `warning` - warning\n\* `info` - info'
        ),
    pagerduty_region: zod
        .enum(['us', 'eu'])
        .describe('\* `us` - us\n\* `eu` - eu')
        .default(alertsDestinationsPagerdutyCreateBodyPagerdutyRegionDefault)
        .describe('Region of the PagerDuty account.\n\n\* `us` - us\n\* `eu` - eu'),
})

/**
 * Send this alert's firings to a Discord or Microsoft Teams channel, or to any webhook. The returned IDs identify the destination.
 */
export const AlertsDestinationsWebhookCreateBody = /* @__PURE__ */ zod.object({
    type: zod
        .enum(['discord', 'teams', 'webhook'])
        .describe('\* `discord` - discord\n\* `teams` - teams\n\* `webhook` - webhook')
        .describe(
            'Destination type: a Discord or Microsoft Teams channel, or any webhook.\n\n\* `discord` - discord\n\* `teams` - teams\n\* `webhook` - webhook'
        ),
    webhook_url: zod
        .string()
        .describe('The https URL to send to. Its path and query are a credential, so reads show only the host.'),
})

/**
 * Simulate a detector on an insight's historical data. No AlertCheck records are created. The AI detector makes a real model call, so that mode needs the 'alert:write' scope.
 */
export const AlertsSimulateCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')
