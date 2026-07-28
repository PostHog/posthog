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

export const billingAlertsCreateBodyThresholdPercentageRegExp = new RegExp('^-?\\d{0,6}(?:\\.\\d{0,2})?$')
export const billingAlertsCreateBodyThresholdValueRegExp = new RegExp('^-?\\d{0,14}(?:\\.\\d{0,6})?$')
export const billingAlertsCreateBodyMinimumValueRegExp = new RegExp('^-?\\d{0,14}(?:\\.\\d{0,6})?$')
export const billingAlertsCreateBodyBaselineWindowDaysMax = 90

export const billingAlertsCreateBodyEvaluationDelayHoursMin = 0
export const billingAlertsCreateBodyEvaluationDelayHoursMax = 72

export const billingAlertsCreateBodyCooldownHoursMin = 0
export const billingAlertsCreateBodyCooldownHoursMax = 720

export const billingAlertsCreateBodyDestinationChangesOneDeleteItemMin = 4
export const billingAlertsCreateBodyDestinationChangesOneDeleteItemMax = 4

export const BillingAlertsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(billingAlertsCreateBodyNameMax).describe('Display name for this billing alert.'),
    description: zod.string().optional().describe('Optional internal description.'),
    enabled: zod.boolean().optional().describe('Whether scheduled checks should evaluate this alert.'),
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
    baseline_window_days: zod
        .number()
        .min(1)
        .max(billingAlertsCreateBodyBaselineWindowDaysMax)
        .optional()
        .describe('Number of preceding UTC billing dates averaged for relative and absolute increase baselines.'),
    evaluation_delay_hours: zod
        .number()
        .min(billingAlertsCreateBodyEvaluationDelayHoursMin)
        .max(billingAlertsCreateBodyEvaluationDelayHoursMax)
        .optional()
        .describe('Hours after a UTC billing date ends before it becomes eligible for evaluation.'),
    cooldown_hours: zod
        .number()
        .min(billingAlertsCreateBodyCooldownHoursMin)
        .max(billingAlertsCreateBodyCooldownHoursMax)
        .optional()
        .describe('Minimum hours between repeated firing notifications.'),
    snoozed_until: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('ISO 8601 timestamp until which evaluation and notifications are snoozed, or null to resume.'),
    destination_changes: zod
        .object({
            delete: zod
                .array(
                    zod
                        .array(zod.uuid())
                        .min(billingAlertsCreateBodyDestinationChangesOneDeleteItemMin)
                        .max(billingAlertsCreateBodyDestinationChangesOneDeleteItemMax)
                )
                .optional(),
            create: zod
                .array(
                    zod.object({
                        type: zod
                            .enum(['slack', 'webhook', 'teams'])
                            .describe('\* `slack` - slack\n\* `webhook` - webhook\n\* `teams` - teams')
                            .describe(
                                'Destination type.\n\n\* `slack` - slack\n\* `webhook` - webhook\n\* `teams` - teams'
                            ),
                        slack_workspace_id: zod
                            .number()
                            .optional()
                            .describe('Slack integration ID in the alert execution project.'),
                        slack_channel_id: zod.string().optional().describe('Slack channel ID for alert delivery.'),
                        slack_channel_name: zod
                            .string()
                            .optional()
                            .describe('Optional Slack channel name shown in the UI.'),
                        webhook_url: zod
                            .url()
                            .optional()
                            .describe('HTTPS webhook URL for webhook or Microsoft Teams delivery.'),
                    })
                )
                .optional(),
        })
        .optional()
        .describe('Destination groups to create or delete in the same transaction as this configuration write.'),
})

export const billingAlertsUpdateBodyNameMax = 160

export const billingAlertsUpdateBodyThresholdPercentageRegExp = new RegExp('^-?\\d{0,6}(?:\\.\\d{0,2})?$')
export const billingAlertsUpdateBodyThresholdValueRegExp = new RegExp('^-?\\d{0,14}(?:\\.\\d{0,6})?$')
export const billingAlertsUpdateBodyMinimumValueRegExp = new RegExp('^-?\\d{0,14}(?:\\.\\d{0,6})?$')
export const billingAlertsUpdateBodyBaselineWindowDaysMax = 90

export const billingAlertsUpdateBodyEvaluationDelayHoursMin = 0
export const billingAlertsUpdateBodyEvaluationDelayHoursMax = 72

export const billingAlertsUpdateBodyCooldownHoursMin = 0
export const billingAlertsUpdateBodyCooldownHoursMax = 720

export const billingAlertsUpdateBodyDestinationChangesOneDeleteItemMin = 4
export const billingAlertsUpdateBodyDestinationChangesOneDeleteItemMax = 4

export const BillingAlertsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(billingAlertsUpdateBodyNameMax).describe('Display name for this billing alert.'),
    description: zod.string().optional().describe('Optional internal description.'),
    enabled: zod.boolean().optional().describe('Whether scheduled checks should evaluate this alert.'),
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
    baseline_window_days: zod
        .number()
        .min(1)
        .max(billingAlertsUpdateBodyBaselineWindowDaysMax)
        .optional()
        .describe('Number of preceding UTC billing dates averaged for relative and absolute increase baselines.'),
    evaluation_delay_hours: zod
        .number()
        .min(billingAlertsUpdateBodyEvaluationDelayHoursMin)
        .max(billingAlertsUpdateBodyEvaluationDelayHoursMax)
        .optional()
        .describe('Hours after a UTC billing date ends before it becomes eligible for evaluation.'),
    cooldown_hours: zod
        .number()
        .min(billingAlertsUpdateBodyCooldownHoursMin)
        .max(billingAlertsUpdateBodyCooldownHoursMax)
        .optional()
        .describe('Minimum hours between repeated firing notifications.'),
    snoozed_until: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('ISO 8601 timestamp until which evaluation and notifications are snoozed, or null to resume.'),
    destination_changes: zod
        .object({
            delete: zod
                .array(
                    zod
                        .array(zod.uuid())
                        .min(billingAlertsUpdateBodyDestinationChangesOneDeleteItemMin)
                        .max(billingAlertsUpdateBodyDestinationChangesOneDeleteItemMax)
                )
                .optional(),
            create: zod
                .array(
                    zod.object({
                        type: zod
                            .enum(['slack', 'webhook', 'teams'])
                            .describe('\* `slack` - slack\n\* `webhook` - webhook\n\* `teams` - teams')
                            .describe(
                                'Destination type.\n\n\* `slack` - slack\n\* `webhook` - webhook\n\* `teams` - teams'
                            ),
                        slack_workspace_id: zod
                            .number()
                            .optional()
                            .describe('Slack integration ID in the alert execution project.'),
                        slack_channel_id: zod.string().optional().describe('Slack channel ID for alert delivery.'),
                        slack_channel_name: zod
                            .string()
                            .optional()
                            .describe('Optional Slack channel name shown in the UI.'),
                        webhook_url: zod
                            .url()
                            .optional()
                            .describe('HTTPS webhook URL for webhook or Microsoft Teams delivery.'),
                    })
                )
                .optional(),
        })
        .optional()
        .describe('Destination groups to create or delete in the same transaction as this configuration write.'),
})

export const billingAlertsPartialUpdateBodyNameMax = 160

export const billingAlertsPartialUpdateBodyThresholdPercentageRegExp = new RegExp('^-?\\d{0,6}(?:\\.\\d{0,2})?$')
export const billingAlertsPartialUpdateBodyThresholdValueRegExp = new RegExp('^-?\\d{0,14}(?:\\.\\d{0,6})?$')
export const billingAlertsPartialUpdateBodyMinimumValueRegExp = new RegExp('^-?\\d{0,14}(?:\\.\\d{0,6})?$')
export const billingAlertsPartialUpdateBodyBaselineWindowDaysMax = 90

export const billingAlertsPartialUpdateBodyEvaluationDelayHoursMin = 0
export const billingAlertsPartialUpdateBodyEvaluationDelayHoursMax = 72

export const billingAlertsPartialUpdateBodyCooldownHoursMin = 0
export const billingAlertsPartialUpdateBodyCooldownHoursMax = 720

export const billingAlertsPartialUpdateBodyDestinationChangesOneDeleteItemMin = 4
export const billingAlertsPartialUpdateBodyDestinationChangesOneDeleteItemMax = 4

export const BillingAlertsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(billingAlertsPartialUpdateBodyNameMax)
        .optional()
        .describe('Display name for this billing alert.'),
    description: zod.string().optional().describe('Optional internal description.'),
    enabled: zod.boolean().optional().describe('Whether scheduled checks should evaluate this alert.'),
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
    baseline_window_days: zod
        .number()
        .min(1)
        .max(billingAlertsPartialUpdateBodyBaselineWindowDaysMax)
        .optional()
        .describe('Number of preceding UTC billing dates averaged for relative and absolute increase baselines.'),
    evaluation_delay_hours: zod
        .number()
        .min(billingAlertsPartialUpdateBodyEvaluationDelayHoursMin)
        .max(billingAlertsPartialUpdateBodyEvaluationDelayHoursMax)
        .optional()
        .describe('Hours after a UTC billing date ends before it becomes eligible for evaluation.'),
    cooldown_hours: zod
        .number()
        .min(billingAlertsPartialUpdateBodyCooldownHoursMin)
        .max(billingAlertsPartialUpdateBodyCooldownHoursMax)
        .optional()
        .describe('Minimum hours between repeated firing notifications.'),
    snoozed_until: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('ISO 8601 timestamp until which evaluation and notifications are snoozed, or null to resume.'),
    destination_changes: zod
        .object({
            delete: zod
                .array(
                    zod
                        .array(zod.uuid())
                        .min(billingAlertsPartialUpdateBodyDestinationChangesOneDeleteItemMin)
                        .max(billingAlertsPartialUpdateBodyDestinationChangesOneDeleteItemMax)
                )
                .optional(),
            create: zod
                .array(
                    zod.object({
                        type: zod
                            .enum(['slack', 'webhook', 'teams'])
                            .describe('\* `slack` - slack\n\* `webhook` - webhook\n\* `teams` - teams')
                            .describe(
                                'Destination type.\n\n\* `slack` - slack\n\* `webhook` - webhook\n\* `teams` - teams'
                            ),
                        slack_workspace_id: zod
                            .number()
                            .optional()
                            .describe('Slack integration ID in the alert execution project.'),
                        slack_channel_id: zod.string().optional().describe('Slack channel ID for alert delivery.'),
                        slack_channel_name: zod
                            .string()
                            .optional()
                            .describe('Optional Slack channel name shown in the UI.'),
                        webhook_url: zod
                            .url()
                            .optional()
                            .describe('HTTPS webhook URL for webhook or Microsoft Teams delivery.'),
                    })
                )
                .optional(),
        })
        .optional()
        .describe('Destination groups to create or delete in the same transaction as this configuration write.'),
})

/**
 * Create a notification destination for this alert. One HogFunction is created per alert event kind.
 */
export const BillingAlertsDestinationsCreateBody = /* @__PURE__ */ zod.object({
    type: zod
        .enum(['slack', 'webhook', 'teams'])
        .describe('\* `slack` - slack\n\* `webhook` - webhook\n\* `teams` - teams')
        .describe('Destination type.\n\n\* `slack` - slack\n\* `webhook` - webhook\n\* `teams` - teams'),
    slack_workspace_id: zod.number().optional().describe('Slack integration ID in the alert execution project.'),
    slack_channel_id: zod.string().optional().describe('Slack channel ID for alert delivery.'),
    slack_channel_name: zod.string().optional().describe('Optional Slack channel name shown in the UI.'),
    webhook_url: zod.url().optional().describe('HTTPS webhook URL for webhook or Microsoft Teams delivery.'),
})

/**
 * Delete a notification destination by deleting its HogFunction group atomically.
 */
export const billingAlertsDestinationsDeleteCreateBodyHogFunctionIdsMin = 4
export const billingAlertsDestinationsDeleteCreateBodyHogFunctionIdsMax = 4

export const BillingAlertsDestinationsDeleteCreateBody = /* @__PURE__ */ zod.object({
    hog_function_ids: zod
        .array(zod.uuid())
        .min(billingAlertsDestinationsDeleteCreateBodyHogFunctionIdsMin)
        .max(billingAlertsDestinationsDeleteCreateBodyHogFunctionIdsMax)
        .describe('HogFunction IDs to delete as one atomic destination group.'),
})
