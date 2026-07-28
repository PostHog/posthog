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

export const billingAlertsCreateBodyNameMax = 160

export const billingAlertsCreateBodyCurrencyMax = 3

export const billingAlertsCreateBodyThresholdPercentageRegExp = new RegExp('^-?\\d{0,6}(?:\\.\\d{0,2})?$')
export const billingAlertsCreateBodyThresholdValueRegExp = new RegExp('^-?\\d{0,14}(?:\\.\\d{0,6})?$')
export const billingAlertsCreateBodyMinimumValueRegExp = new RegExp('^-?\\d{0,14}(?:\\.\\d{0,6})?$')
export const billingAlertsCreateBodyBaselineWindowDaysMax = 90

export const billingAlertsCreateBodyEvaluationDelayHoursMin = 0
export const billingAlertsCreateBodyEvaluationDelayHoursMax = 72

export const billingAlertsCreateBodyCheckIntervalHoursMax = 24

export const billingAlertsCreateBodyCooldownHoursMin = 0
export const billingAlertsCreateBodyCooldownHoursMax = 720

export const BillingAlertsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(billingAlertsCreateBodyNameMax).describe('Display name for this billing alert.'),
    description: zod.string().optional().describe('Optional internal description.'),
    enabled: zod.boolean().optional().describe('Whether scheduled checks should evaluate this alert.'),
    metric: zod
        .enum(['spend', 'usage'])
        .describe('\* `spend` - Spend\n\* `usage` - Usage')
        .optional()
        .describe('Billing metric to evaluate: spend or usage.\n\n\* `spend` - Spend\n\* `usage` - Usage'),
    currency: zod.string().max(billingAlertsCreateBodyCurrencyMax).optional().describe('Currency for spend alerts.'),
    threshold_type: zod
        .enum(['relative_increase', 'absolute_value', 'absolute_increase'])
        .describe(
            '\* `relative_increase` - Relative increase\n\* `absolute_value` - Absolute value\n\* `absolute_increase` - Absolute increase'
        )
        .optional()
        .describe(
            'Threshold rule type.\n\n\* `relative_increase` - Relative increase\n\* `absolute_value` - Absolute value\n\* `absolute_increase` - Absolute increase'
        ),
    threshold_percentage: zod
        .stringFormat('decimal', billingAlertsCreateBodyThresholdPercentageRegExp)
        .nullish()
        .describe('Percentage increase that triggers relative increase alerts.'),
    threshold_value: zod
        .stringFormat('decimal', billingAlertsCreateBodyThresholdValueRegExp)
        .nullish()
        .describe('Absolute value or absolute increase that triggers absolute threshold alerts.'),
    minimum_value: zod
        .stringFormat('decimal', billingAlertsCreateBodyMinimumValueRegExp)
        .optional()
        .describe('Minimum current value before the alert can fire.'),
    baseline_window_days: zod.number().min(1).max(billingAlertsCreateBodyBaselineWindowDaysMax).optional(),
    evaluation_delay_hours: zod
        .number()
        .min(billingAlertsCreateBodyEvaluationDelayHoursMin)
        .max(billingAlertsCreateBodyEvaluationDelayHoursMax)
        .optional(),
    check_interval_hours: zod.number().min(1).max(billingAlertsCreateBodyCheckIntervalHoursMax).optional(),
    cooldown_hours: zod
        .number()
        .min(billingAlertsCreateBodyCooldownHoursMin)
        .max(billingAlertsCreateBodyCooldownHoursMax)
        .optional(),
    snooze_until: zod.iso.datetime({ offset: true }).nullish(),
})

export const billingAlertsUpdateBodyNameMax = 160

export const billingAlertsUpdateBodyCurrencyMax = 3

export const billingAlertsUpdateBodyThresholdPercentageRegExp = new RegExp('^-?\\d{0,6}(?:\\.\\d{0,2})?$')
export const billingAlertsUpdateBodyThresholdValueRegExp = new RegExp('^-?\\d{0,14}(?:\\.\\d{0,6})?$')
export const billingAlertsUpdateBodyMinimumValueRegExp = new RegExp('^-?\\d{0,14}(?:\\.\\d{0,6})?$')
export const billingAlertsUpdateBodyBaselineWindowDaysMax = 90

export const billingAlertsUpdateBodyEvaluationDelayHoursMin = 0
export const billingAlertsUpdateBodyEvaluationDelayHoursMax = 72

export const billingAlertsUpdateBodyCheckIntervalHoursMax = 24

export const billingAlertsUpdateBodyCooldownHoursMin = 0
export const billingAlertsUpdateBodyCooldownHoursMax = 720

export const BillingAlertsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(billingAlertsUpdateBodyNameMax).describe('Display name for this billing alert.'),
    description: zod.string().optional().describe('Optional internal description.'),
    enabled: zod.boolean().optional().describe('Whether scheduled checks should evaluate this alert.'),
    metric: zod
        .enum(['spend', 'usage'])
        .describe('\* `spend` - Spend\n\* `usage` - Usage')
        .optional()
        .describe('Billing metric to evaluate: spend or usage.\n\n\* `spend` - Spend\n\* `usage` - Usage'),
    currency: zod.string().max(billingAlertsUpdateBodyCurrencyMax).optional().describe('Currency for spend alerts.'),
    threshold_type: zod
        .enum(['relative_increase', 'absolute_value', 'absolute_increase'])
        .describe(
            '\* `relative_increase` - Relative increase\n\* `absolute_value` - Absolute value\n\* `absolute_increase` - Absolute increase'
        )
        .optional()
        .describe(
            'Threshold rule type.\n\n\* `relative_increase` - Relative increase\n\* `absolute_value` - Absolute value\n\* `absolute_increase` - Absolute increase'
        ),
    threshold_percentage: zod
        .stringFormat('decimal', billingAlertsUpdateBodyThresholdPercentageRegExp)
        .nullish()
        .describe('Percentage increase that triggers relative increase alerts.'),
    threshold_value: zod
        .stringFormat('decimal', billingAlertsUpdateBodyThresholdValueRegExp)
        .nullish()
        .describe('Absolute value or absolute increase that triggers absolute threshold alerts.'),
    minimum_value: zod
        .stringFormat('decimal', billingAlertsUpdateBodyMinimumValueRegExp)
        .optional()
        .describe('Minimum current value before the alert can fire.'),
    baseline_window_days: zod.number().min(1).max(billingAlertsUpdateBodyBaselineWindowDaysMax).optional(),
    evaluation_delay_hours: zod
        .number()
        .min(billingAlertsUpdateBodyEvaluationDelayHoursMin)
        .max(billingAlertsUpdateBodyEvaluationDelayHoursMax)
        .optional(),
    check_interval_hours: zod.number().min(1).max(billingAlertsUpdateBodyCheckIntervalHoursMax).optional(),
    cooldown_hours: zod
        .number()
        .min(billingAlertsUpdateBodyCooldownHoursMin)
        .max(billingAlertsUpdateBodyCooldownHoursMax)
        .optional(),
    snooze_until: zod.iso.datetime({ offset: true }).nullish(),
})

export const billingAlertsPartialUpdateBodyNameMax = 160

export const billingAlertsPartialUpdateBodyCurrencyMax = 3

export const billingAlertsPartialUpdateBodyThresholdPercentageRegExp = new RegExp('^-?\\d{0,6}(?:\\.\\d{0,2})?$')
export const billingAlertsPartialUpdateBodyThresholdValueRegExp = new RegExp('^-?\\d{0,14}(?:\\.\\d{0,6})?$')
export const billingAlertsPartialUpdateBodyMinimumValueRegExp = new RegExp('^-?\\d{0,14}(?:\\.\\d{0,6})?$')
export const billingAlertsPartialUpdateBodyBaselineWindowDaysMax = 90

export const billingAlertsPartialUpdateBodyEvaluationDelayHoursMin = 0
export const billingAlertsPartialUpdateBodyEvaluationDelayHoursMax = 72

export const billingAlertsPartialUpdateBodyCheckIntervalHoursMax = 24

export const billingAlertsPartialUpdateBodyCooldownHoursMin = 0
export const billingAlertsPartialUpdateBodyCooldownHoursMax = 720

export const BillingAlertsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(billingAlertsPartialUpdateBodyNameMax)
        .optional()
        .describe('Display name for this billing alert.'),
    description: zod.string().optional().describe('Optional internal description.'),
    enabled: zod.boolean().optional().describe('Whether scheduled checks should evaluate this alert.'),
    metric: zod
        .enum(['spend', 'usage'])
        .describe('\* `spend` - Spend\n\* `usage` - Usage')
        .optional()
        .describe('Billing metric to evaluate: spend or usage.\n\n\* `spend` - Spend\n\* `usage` - Usage'),
    currency: zod
        .string()
        .max(billingAlertsPartialUpdateBodyCurrencyMax)
        .optional()
        .describe('Currency for spend alerts.'),
    threshold_type: zod
        .enum(['relative_increase', 'absolute_value', 'absolute_increase'])
        .describe(
            '\* `relative_increase` - Relative increase\n\* `absolute_value` - Absolute value\n\* `absolute_increase` - Absolute increase'
        )
        .optional()
        .describe(
            'Threshold rule type.\n\n\* `relative_increase` - Relative increase\n\* `absolute_value` - Absolute value\n\* `absolute_increase` - Absolute increase'
        ),
    threshold_percentage: zod
        .stringFormat('decimal', billingAlertsPartialUpdateBodyThresholdPercentageRegExp)
        .nullish()
        .describe('Percentage increase that triggers relative increase alerts.'),
    threshold_value: zod
        .stringFormat('decimal', billingAlertsPartialUpdateBodyThresholdValueRegExp)
        .nullish()
        .describe('Absolute value or absolute increase that triggers absolute threshold alerts.'),
    minimum_value: zod
        .stringFormat('decimal', billingAlertsPartialUpdateBodyMinimumValueRegExp)
        .optional()
        .describe('Minimum current value before the alert can fire.'),
    baseline_window_days: zod.number().min(1).max(billingAlertsPartialUpdateBodyBaselineWindowDaysMax).optional(),
    evaluation_delay_hours: zod
        .number()
        .min(billingAlertsPartialUpdateBodyEvaluationDelayHoursMin)
        .max(billingAlertsPartialUpdateBodyEvaluationDelayHoursMax)
        .optional(),
    check_interval_hours: zod.number().min(1).max(billingAlertsPartialUpdateBodyCheckIntervalHoursMax).optional(),
    cooldown_hours: zod
        .number()
        .min(billingAlertsPartialUpdateBodyCooldownHoursMin)
        .max(billingAlertsPartialUpdateBodyCooldownHoursMax)
        .optional(),
    snooze_until: zod.iso.datetime({ offset: true }).nullish(),
})

/**
 * Create a notification destination for this alert. One HogFunction is created per alert event kind.
 */
export const BillingAlertsDestinationsCreateBody = /* @__PURE__ */ zod.object({
    type: zod
        .enum(['slack', 'webhook', 'teams'])
        .describe('\* `slack` - slack\n\* `webhook` - webhook\n\* `teams` - teams')
        .describe('Destination type.\n\n\* `slack` - slack\n\* `webhook` - webhook\n\* `teams` - teams'),
    slack_workspace_id: zod
        .number()
        .optional()
        .describe('Integration ID for the Slack workspace. Required when type=slack.'),
    slack_channel_id: zod.string().optional().describe('Slack channel ID. Required when type=slack.'),
    slack_channel_name: zod.string().optional().describe('Human-readable channel name for display.'),
    webhook_url: zod
        .url()
        .optional()
        .describe('HTTPS endpoint to POST to. Required when type=webhook, or the Teams webhook URL when type=teams.'),
})

/**
 * Delete a notification destination by deleting its HogFunction group atomically.
 */

export const BillingAlertsDestinationsDeleteCreateBody = /* @__PURE__ */ zod.object({
    hog_function_ids: zod
        .array(zod.uuid())
        .min(1)
        .describe('HogFunction IDs to delete as one atomic destination group.'),
})
