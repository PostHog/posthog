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
 * The billing API at /api/billing/:organization_id/, which names the organization instead of following the
 * user's current project.
 */
export const BillingOrganizationPartialUpdateBody = /* @__PURE__ */ zod.object({
    custom_limits_usd: zod
        .record(zod.string(), zod.number().nullable())
        .optional()
        .describe('Spend limit in USD for each product or usage key. Null removes the limit for that key.'),
    reset_limit_next_period: zod
        .string()
        .optional()
        .describe('Product type whose limit for the next billing period is removed.'),
})

/**
 * The billing API at /api/billing/:organization_id/, which names the organization instead of following the
 * user's current project.
 */
export const BillingOrganizationActivateCreateBody = /* @__PURE__ */ zod.object({
    organization_id: zod.uuid().describe('Organization selected when this payment flow started.'),
    products: zod.string().optional().describe('Product and plan keys to activate.'),
    intent_product: zod.string().optional().describe('Product that prompted the subscription upgrade.'),
    custom_limits_usd: zod.string().optional().describe('JSON-encoded custom product limits to apply on activation.'),
})

/**
 * The billing API at /api/billing/:organization_id/, which names the organization instead of following the
 * user's current project.
 */
export const BillingOrganizationActivateAuthorizeCreateBody = /* @__PURE__ */ zod.object({
    organization_id: zod.uuid().describe('Organization selected when this payment flow started.'),
})

/**
 * The billing API at /api/billing/:organization_id/, which names the organization instead of following the
 * user's current project.
 */
export const BillingOrganizationActivateAuthorizeStatusCreateBody = /* @__PURE__ */ zod.object({
    organization_id: zod.uuid().describe('Organization selected when this payment flow started.'),
    payment_intent_id: zod.string().nullish().describe('Stripe payment intent created for this organization.'),
})

/**
 * The billing API at /api/billing/:organization_id/, which names the organization instead of following the
 * user's current project.
 */
export const BillingOrganizationCouponsClaimCreateBody = /* @__PURE__ */ zod.object({
    code: zod
        .string()
        .optional()
        .describe('Coupon code to redeem. Give this or `campaign_slug`, never both. Needs billing access.'),
    campaign_slug: zod
        .string()
        .optional()
        .describe(
            'Slug of a campaign to redeem. Give this or `code`, never both. Any organization member can redeem an allowlisted campaign.'
        ),
})

/**
 * The billing API at /api/billing/:organization_id/, which names the organization instead of following the
 * user's current project.
 */
export const BillingOrganizationCreditsPurchaseCreateBody = /* @__PURE__ */ zod.object({
    annual_credit_amount_usd: zod.number().describe('Amount of credits in USD to buy for one year.'),
    collection_method: zod
        .string()
        .describe('How to pay: `charge_automatically` charges the card on file, `send_invoice` emails an invoice.'),
})

/**
 * The billing API at /api/billing/:organization_id/, which names the organization instead of following the
 * user's current project.
 */
export const BillingOrganizationDeactivateCreateBody = /* @__PURE__ */ zod.object({
    products: zod.string().describe('Comma-separated product types to unsubscribe from.'),
})

/**
 * The billing API at /api/billing/:organization_id/, which names the organization instead of following the
 * user's current project.
 */
export const BillingOrganizationLicensePartialUpdateBody = /* @__PURE__ */ zod.object({
    license: zod.string().optional().describe('License key to activate on this self-hosted instance.'),
})

/**
 * The billing API at /api/billing/:organization_id/, which names the organization instead of following the
 * user's current project.
 */
export const BillingOrganizationStartupsApplyCreateBody = /* @__PURE__ */ zod.object({
    organization_id: zod.uuid().describe('Organization that applies to the startup program.'),
    program: zod.string().describe('Program to apply to: `YC` or `startup`.'),
    yc_merch_count: zod.number().nullish().describe('Number of YC merch items the founders want.'),
    yc_verification_url: zod.string().nullish().describe('YC Bookface link that proves the founder is in YC.'),
    yc_batch: zod.string().nullish().describe('YC batch, for example `W25`.'),
    yc_proof_screenshot_url: zod.string().nullish().describe('Uploaded screenshot that proves the founder is in YC.'),
    raised: zod.string().nullish().describe('Total funding raised, in USD.'),
    incorporation_date: zod.iso.date().nullish().describe('Date the company was incorporated, as YYYY-MM-DD.'),
    referrer: zod.string().nullish().describe('Partner that referred the startup, in lowercase.'),
})

/**
 * The billing API at /api/billing/:organization_id/, which names the organization instead of following the
 * user's current project.
 */
export const BillingOrganizationSubscriptionSwitchPlanCreateBody = /* @__PURE__ */ zod.object({
    from_product_key: zod.string().describe('Product the organization is subscribed to now.'),
    from_plan_key: zod.string().describe('Plan the organization is subscribed to now.'),
    to_product_key: zod.string().describe('Product to switch to.'),
    to_plan_key: zod.string().describe('Plan to switch to.'),
})

/**
 * The billing API at /api/billing/:organization_id/, which names the organization instead of following the
 * user's current project.
 */
export const BillingOrganizationTrialsActivateCreateBody = /* @__PURE__ */ zod.object({
    type: zod.string().describe('Trial type: `autosubscribe` or `standard`.'),
    target: zod.string().describe('Product type or plan the trial is for.'),
})

export const BillingPartialUpdateBody = /* @__PURE__ */ zod.object({
    custom_limits_usd: zod
        .record(zod.string(), zod.number().nullable())
        .optional()
        .describe('Spend limit in USD for each product or usage key. Null removes the limit for that key.'),
    reset_limit_next_period: zod
        .string()
        .optional()
        .describe('Product type whose limit for the next billing period is removed.'),
})

export const BillingActivateCreateBody = /* @__PURE__ */ zod.object({
    organization_id: zod.uuid().describe('Organization selected when this payment flow started.'),
    products: zod.string().optional().describe('Product and plan keys to activate.'),
    intent_product: zod.string().optional().describe('Product that prompted the subscription upgrade.'),
    custom_limits_usd: zod.string().optional().describe('JSON-encoded custom product limits to apply on activation.'),
})

export const BillingActivateAuthorizeCreateBody = /* @__PURE__ */ zod.object({
    organization_id: zod.uuid().describe('Organization selected when this payment flow started.'),
})

export const BillingActivateAuthorizeStatusCreateBody = /* @__PURE__ */ zod.object({
    organization_id: zod.uuid().describe('Organization selected when this payment flow started.'),
    payment_intent_id: zod.string().nullish().describe('Stripe payment intent created for this organization.'),
})

export const BillingCouponsClaimCreateBody = /* @__PURE__ */ zod.object({
    code: zod
        .string()
        .optional()
        .describe('Coupon code to redeem. Give this or `campaign_slug`, never both. Needs billing access.'),
    campaign_slug: zod
        .string()
        .optional()
        .describe(
            'Slug of a campaign to redeem. Give this or `code`, never both. Any organization member can redeem an allowlisted campaign.'
        ),
})

export const BillingCreditsPurchaseCreateBody = /* @__PURE__ */ zod.object({
    annual_credit_amount_usd: zod.number().describe('Amount of credits in USD to buy for one year.'),
    collection_method: zod
        .string()
        .describe('How to pay: `charge_automatically` charges the card on file, `send_invoice` emails an invoice.'),
})

export const BillingDeactivateCreateBody = /* @__PURE__ */ zod.object({
    products: zod.string().describe('Comma-separated product types to unsubscribe from.'),
})

export const BillingLicensePartialUpdateBody = /* @__PURE__ */ zod.object({
    license: zod.string().optional().describe('License key to activate on this self-hosted instance.'),
})

export const BillingStartupsApplyCreateBody = /* @__PURE__ */ zod.object({
    organization_id: zod.uuid().describe('Organization that applies to the startup program.'),
    program: zod.string().describe('Program to apply to: `YC` or `startup`.'),
    yc_merch_count: zod.number().nullish().describe('Number of YC merch items the founders want.'),
    yc_verification_url: zod.string().nullish().describe('YC Bookface link that proves the founder is in YC.'),
    yc_batch: zod.string().nullish().describe('YC batch, for example `W25`.'),
    yc_proof_screenshot_url: zod.string().nullish().describe('Uploaded screenshot that proves the founder is in YC.'),
    raised: zod.string().nullish().describe('Total funding raised, in USD.'),
    incorporation_date: zod.iso.date().nullish().describe('Date the company was incorporated, as YYYY-MM-DD.'),
    referrer: zod.string().nullish().describe('Partner that referred the startup, in lowercase.'),
})

export const BillingSubscriptionSwitchPlanCreateBody = /* @__PURE__ */ zod.object({
    from_product_key: zod.string().describe('Product the organization is subscribed to now.'),
    from_plan_key: zod.string().describe('Plan the organization is subscribed to now.'),
    to_product_key: zod.string().describe('Product to switch to.'),
    to_plan_key: zod.string().describe('Plan to switch to.'),
})

export const BillingTrialsActivateCreateBody = /* @__PURE__ */ zod.object({
    type: zod.string().describe('Trial type: `autosubscribe` or `standard`.'),
    target: zod.string().describe('Product type or plan the trial is for.'),
})

export const billingAlertsCreateBodyNameMax = 160

export const billingAlertsCreateBodyThresholdPercentageRegExp = new RegExp('^-?\\d{0,6}(?:\\.\\d{0,2})?$')
export const billingAlertsCreateBodyThresholdValueRegExp = new RegExp('^-?\\d{0,14}(?:\\.\\d{0,6})?$')
export const billingAlertsCreateBodyBaselineWindowDaysMax = 90

export const billingAlertsCreateBodyDestinationChangesOneDeleteItemMax = 100

export const BillingAlertsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(billingAlertsCreateBodyNameMax).describe('Display name for this billing alert.'),
    description: zod.string().optional().describe('Optional internal description.'),
    enabled: zod.boolean().optional().describe('Whether scheduled checks should evaluate this alert.'),
    metric: zod
        .enum(['spend', 'projected_spend'])
        .describe('\* `spend` - Spend\n\* `projected_spend` - Projected spend')
        .optional()
        .describe(
            'Billing-period total to evaluate: current spend so far, or projected period-end spend.\n\n\* `spend` - Spend\n\* `projected_spend` - Projected spend'
        ),
    threshold_type: zod
        .enum(['relative_increase', 'absolute_value', 'absolute_increase'])
        .describe(
            '\* `relative_increase` - Relative increase\n\* `absolute_value` - Absolute value\n\* `absolute_increase` - Absolute increase'
        )
        .optional()
        .describe(
            'Threshold rule type. The first version supports absolute value only.\n\n\* `relative_increase` - Relative increase\n\* `absolute_value` - Absolute value\n\* `absolute_increase` - Absolute increase'
        ),
    threshold_percentage: zod
        .stringFormat('decimal', billingAlertsCreateBodyThresholdPercentageRegExp)
        .nullish()
        .describe('Reserved for future increase-over-baseline rules. Not used by absolute value alerts.'),
    threshold_value: zod
        .stringFormat('decimal', billingAlertsCreateBodyThresholdValueRegExp)
        .nullish()
        .describe('Absolute value or absolute increase that triggers absolute threshold alerts.'),
    baseline_window_days: zod
        .number()
        .min(1)
        .max(billingAlertsCreateBodyBaselineWindowDaysMax)
        .optional()
        .describe('Reserved for future increase-over-baseline rules. Not used by absolute value alerts.'),
    snoozed_until: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('ISO 8601 timestamp until which evaluation and notifications are snoozed, or null to resume.'),
    destination_changes: zod
        .object({
            delete: zod
                .array(zod.array(zod.uuid()).min(1).max(billingAlertsCreateBodyDestinationChangesOneDeleteItemMax))
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
export const billingAlertsUpdateBodyBaselineWindowDaysMax = 90

export const billingAlertsUpdateBodyDestinationChangesOneDeleteItemMax = 100

export const BillingAlertsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(billingAlertsUpdateBodyNameMax).describe('Display name for this billing alert.'),
    description: zod.string().optional().describe('Optional internal description.'),
    enabled: zod.boolean().optional().describe('Whether scheduled checks should evaluate this alert.'),
    metric: zod
        .enum(['spend', 'projected_spend'])
        .describe('\* `spend` - Spend\n\* `projected_spend` - Projected spend')
        .optional()
        .describe(
            'Billing-period total to evaluate: current spend so far, or projected period-end spend.\n\n\* `spend` - Spend\n\* `projected_spend` - Projected spend'
        ),
    threshold_type: zod
        .enum(['relative_increase', 'absolute_value', 'absolute_increase'])
        .describe(
            '\* `relative_increase` - Relative increase\n\* `absolute_value` - Absolute value\n\* `absolute_increase` - Absolute increase'
        )
        .optional()
        .describe(
            'Threshold rule type. The first version supports absolute value only.\n\n\* `relative_increase` - Relative increase\n\* `absolute_value` - Absolute value\n\* `absolute_increase` - Absolute increase'
        ),
    threshold_percentage: zod
        .stringFormat('decimal', billingAlertsUpdateBodyThresholdPercentageRegExp)
        .nullish()
        .describe('Reserved for future increase-over-baseline rules. Not used by absolute value alerts.'),
    threshold_value: zod
        .stringFormat('decimal', billingAlertsUpdateBodyThresholdValueRegExp)
        .nullish()
        .describe('Absolute value or absolute increase that triggers absolute threshold alerts.'),
    baseline_window_days: zod
        .number()
        .min(1)
        .max(billingAlertsUpdateBodyBaselineWindowDaysMax)
        .optional()
        .describe('Reserved for future increase-over-baseline rules. Not used by absolute value alerts.'),
    snoozed_until: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('ISO 8601 timestamp until which evaluation and notifications are snoozed, or null to resume.'),
    destination_changes: zod
        .object({
            delete: zod
                .array(zod.array(zod.uuid()).min(1).max(billingAlertsUpdateBodyDestinationChangesOneDeleteItemMax))
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
export const billingAlertsPartialUpdateBodyBaselineWindowDaysMax = 90

export const billingAlertsPartialUpdateBodyDestinationChangesOneDeleteItemMax = 100

export const BillingAlertsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(billingAlertsPartialUpdateBodyNameMax)
        .optional()
        .describe('Display name for this billing alert.'),
    description: zod.string().optional().describe('Optional internal description.'),
    enabled: zod.boolean().optional().describe('Whether scheduled checks should evaluate this alert.'),
    metric: zod
        .enum(['spend', 'projected_spend'])
        .describe('\* `spend` - Spend\n\* `projected_spend` - Projected spend')
        .optional()
        .describe(
            'Billing-period total to evaluate: current spend so far, or projected period-end spend.\n\n\* `spend` - Spend\n\* `projected_spend` - Projected spend'
        ),
    threshold_type: zod
        .enum(['relative_increase', 'absolute_value', 'absolute_increase'])
        .describe(
            '\* `relative_increase` - Relative increase\n\* `absolute_value` - Absolute value\n\* `absolute_increase` - Absolute increase'
        )
        .optional()
        .describe(
            'Threshold rule type. The first version supports absolute value only.\n\n\* `relative_increase` - Relative increase\n\* `absolute_value` - Absolute value\n\* `absolute_increase` - Absolute increase'
        ),
    threshold_percentage: zod
        .stringFormat('decimal', billingAlertsPartialUpdateBodyThresholdPercentageRegExp)
        .nullish()
        .describe('Reserved for future increase-over-baseline rules. Not used by absolute value alerts.'),
    threshold_value: zod
        .stringFormat('decimal', billingAlertsPartialUpdateBodyThresholdValueRegExp)
        .nullish()
        .describe('Absolute value or absolute increase that triggers absolute threshold alerts.'),
    baseline_window_days: zod
        .number()
        .min(1)
        .max(billingAlertsPartialUpdateBodyBaselineWindowDaysMax)
        .optional()
        .describe('Reserved for future increase-over-baseline rules. Not used by absolute value alerts.'),
    snoozed_until: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('ISO 8601 timestamp until which evaluation and notifications are snoozed, or null to resume.'),
    destination_changes: zod
        .object({
            delete: zod
                .array(
                    zod.array(zod.uuid()).min(1).max(billingAlertsPartialUpdateBodyDestinationChangesOneDeleteItemMax)
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
export const billingAlertsDestinationsDeleteCreateBodyHogFunctionIdsMax = 100

export const BillingAlertsDestinationsDeleteCreateBody = /* @__PURE__ */ zod.object({
    hog_function_ids: zod
        .array(zod.uuid())
        .min(1)
        .max(billingAlertsDestinationsDeleteCreateBodyHogFunctionIdsMax)
        .describe('HogFunction IDs to delete as one atomic destination group.'),
})
