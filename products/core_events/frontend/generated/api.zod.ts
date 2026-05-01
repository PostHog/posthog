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

/**
 * CRUD operations for Core Events.

Core events are reusable event definitions that can be shared across
Marketing analytics, Customer analytics, and Revenue analytics.
 */
export const coreEventsCreateBodyNameMax = 255

export const CoreEventsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(coreEventsCreateBodyNameMax).describe('Display name for this core event'),
    description: zod.string().optional().describe('Optional description'),
    category: zod
        .enum([
            'acquisition',
            'activation',
            'monetization',
            'expansion',
            'referral',
            'retention',
            'churn',
            'reactivation',
        ])
        .describe(
            '* `acquisition` - Acquisition\n* `activation` - Activation\n* `monetization` - Monetization\n* `expansion` - Expansion\n* `referral` - Referral\n* `retention` - Retention\n* `churn` - Churn\n* `reactivation` - Reactivation'
        )
        .describe(
            'Lifecycle category for this core event\n\n* `acquisition` - Acquisition\n* `activation` - Activation\n* `monetization` - Monetization\n* `expansion` - Expansion\n* `referral` - Referral\n* `retention` - Retention\n* `churn` - Churn\n* `reactivation` - Reactivation'
        ),
    filter: zod.unknown().describe('Filter configuration - event, action, or data warehouse node'),
})

/**
 * CRUD operations for Core Events.

Core events are reusable event definitions that can be shared across
Marketing analytics, Customer analytics, and Revenue analytics.
 */
export const coreEventsUpdateBodyNameMax = 255

export const CoreEventsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(coreEventsUpdateBodyNameMax).describe('Display name for this core event'),
    description: zod.string().optional().describe('Optional description'),
    category: zod
        .enum([
            'acquisition',
            'activation',
            'monetization',
            'expansion',
            'referral',
            'retention',
            'churn',
            'reactivation',
        ])
        .describe(
            '* `acquisition` - Acquisition\n* `activation` - Activation\n* `monetization` - Monetization\n* `expansion` - Expansion\n* `referral` - Referral\n* `retention` - Retention\n* `churn` - Churn\n* `reactivation` - Reactivation'
        )
        .describe(
            'Lifecycle category for this core event\n\n* `acquisition` - Acquisition\n* `activation` - Activation\n* `monetization` - Monetization\n* `expansion` - Expansion\n* `referral` - Referral\n* `retention` - Retention\n* `churn` - Churn\n* `reactivation` - Reactivation'
        ),
    filter: zod.unknown().describe('Filter configuration - event, action, or data warehouse node'),
})

/**
 * CRUD operations for Core Events.

Core events are reusable event definitions that can be shared across
Marketing analytics, Customer analytics, and Revenue analytics.
 */
export const coreEventsPartialUpdateBodyNameMax = 255

export const CoreEventsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(coreEventsPartialUpdateBodyNameMax).optional().describe('Display name for this core event'),
    description: zod.string().optional().describe('Optional description'),
    category: zod
        .enum([
            'acquisition',
            'activation',
            'monetization',
            'expansion',
            'referral',
            'retention',
            'churn',
            'reactivation',
        ])
        .describe(
            '* `acquisition` - Acquisition\n* `activation` - Activation\n* `monetization` - Monetization\n* `expansion` - Expansion\n* `referral` - Referral\n* `retention` - Retention\n* `churn` - Churn\n* `reactivation` - Reactivation'
        )
        .optional()
        .describe(
            'Lifecycle category for this core event\n\n* `acquisition` - Acquisition\n* `activation` - Activation\n* `monetization` - Monetization\n* `expansion` - Expansion\n* `referral` - Referral\n* `retention` - Retention\n* `churn` - Churn\n* `reactivation` - Reactivation'
        ),
    filter: zod.unknown().optional().describe('Filter configuration - event, action, or data warehouse node'),
})
