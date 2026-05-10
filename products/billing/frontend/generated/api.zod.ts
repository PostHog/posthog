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

export const billingPartialUpdateBodyPlanMax = 100

export const BillingPartialUpdateBody = /* @__PURE__ */ zod.object({
    plan: zod.string().max(billingPartialUpdateBodyPlanMax).optional(),
    billing_limit: zod.number().optional(),
})

export const billingActivateCreateBodyPlanMax = 100

export const BillingActivateCreateBody = /* @__PURE__ */ zod.object({
    plan: zod.string().max(billingActivateCreateBodyPlanMax),
    billing_limit: zod.number(),
})

export const billingActivateAuthorizeCreateBodyPlanMax = 100

export const BillingActivateAuthorizeCreateBody = /* @__PURE__ */ zod.object({
    plan: zod.string().max(billingActivateAuthorizeCreateBodyPlanMax),
    billing_limit: zod.number(),
})

export const billingActivateAuthorizeStatusCreateBodyPlanMax = 100

export const BillingActivateAuthorizeStatusCreateBody = /* @__PURE__ */ zod.object({
    plan: zod.string().max(billingActivateAuthorizeStatusCreateBodyPlanMax),
    billing_limit: zod.number(),
})

export const billingCouponsClaimCreateBodyPlanMax = 100

export const BillingCouponsClaimCreateBody = /* @__PURE__ */ zod.object({
    plan: zod.string().max(billingCouponsClaimCreateBodyPlanMax),
    billing_limit: zod.number(),
})

export const billingCreditsPurchaseCreateBodyPlanMax = 100

export const BillingCreditsPurchaseCreateBody = /* @__PURE__ */ zod.object({
    plan: zod.string().max(billingCreditsPurchaseCreateBodyPlanMax),
    billing_limit: zod.number(),
})

export const billingDeactivateCreateBodyPlanMax = 100

export const BillingDeactivateCreateBody = /* @__PURE__ */ zod.object({
    plan: zod.string().max(billingDeactivateCreateBodyPlanMax),
    billing_limit: zod.number(),
})

export const billingLicensePartialUpdateBodyPlanMax = 100

export const BillingLicensePartialUpdateBody = /* @__PURE__ */ zod.object({
    plan: zod.string().max(billingLicensePartialUpdateBodyPlanMax).optional(),
    billing_limit: zod.number().optional(),
})

export const billingStartupsApplyCreateBodyPlanMax = 100

export const BillingStartupsApplyCreateBody = /* @__PURE__ */ zod.object({
    plan: zod.string().max(billingStartupsApplyCreateBodyPlanMax),
    billing_limit: zod.number(),
})

export const billingSubscriptionSwitchPlanCreateBodyPlanMax = 100

export const BillingSubscriptionSwitchPlanCreateBody = /* @__PURE__ */ zod.object({
    plan: zod.string().max(billingSubscriptionSwitchPlanCreateBodyPlanMax),
    billing_limit: zod.number(),
})

export const billingTrialsActivateCreateBodyPlanMax = 100

export const BillingTrialsActivateCreateBody = /* @__PURE__ */ zod.object({
    plan: zod.string().max(billingTrialsActivateCreateBodyPlanMax),
    billing_limit: zod.number(),
})

export const billingTrialsCancelCreateBodyPlanMax = 100

export const BillingTrialsCancelCreateBody = /* @__PURE__ */ zod.object({
    plan: zod.string().max(billingTrialsCancelCreateBodyPlanMax),
    billing_limit: zod.number(),
})
