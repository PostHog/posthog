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

export const AlertsDestinationsDeleteCreateBody = /* @__PURE__ */ zod.object({
    hog_function_ids: zod
        .array(zod.uuid())
        .min(1)
        .max(alertsDestinationsDeleteCreateBodyHogFunctionIdsMax)
        .describe('Destination IDs to delete, as returned when the destination was created.'),
})

/**
 * Simulate a detector on an insight's historical data. Read-only — no AlertCheck records are created.
 */
export const AlertsSimulateCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')
