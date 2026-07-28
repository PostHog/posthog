import { AvailableFeature, BillingFeatureType, BillingPlan, BillingPlanType, BillingType } from '~/types'

export const KNOWN_ENTERPRISE_ORG_IDS = ['018713f3-8d56-0000-32fa-75ce97e6662f']

export type SupportPlanKey = BillingPlan | 'boost_trial' | 'scale_trial'

export function getResponseTimeFeature(
    supportPlans: BillingPlanType[] | null | undefined,
    planName: string
): BillingFeatureType | undefined {
    const plan = supportPlans?.find((p) => p.name?.includes(planName))
    return plan?.features?.find((f) => f.key === AvailableFeature.SUPPORT_RESPONSE_TIME)
}

export function getCurrentSupportPlanKey(
    billing: BillingType | null | undefined,
    billingPlan: BillingPlan | null,
    organizationId: string | null | undefined
): SupportPlanKey {
    const isKnownEnterpriseOrg = KNOWN_ENTERPRISE_ORG_IDS.includes(organizationId || '')
    const activeTrialTarget = billing?.trial?.status === 'active' ? billing.trial.target : undefined
    if (isKnownEnterpriseOrg || activeTrialTarget === 'enterprise' || billingPlan === BillingPlan.Enterprise) {
        return BillingPlan.Enterprise
    }
    if (activeTrialTarget === 'scale') {
        return 'scale_trial'
    }
    if (activeTrialTarget === 'boost') {
        return 'boost_trial'
    }
    return billingPlan || BillingPlan.Free
}

const SUPPORT_PLAN_NAMES: Partial<Record<SupportPlanKey, string>> = {
    [BillingPlan.Boost]: 'Boost',
    [BillingPlan.Teams]: 'Teams',
    [BillingPlan.Scale]: 'Scale',
    [BillingPlan.Enterprise]: 'Enterprise',
}

export function getSupportResponseTime(
    billing: BillingType | null | undefined,
    supportPlans: BillingPlanType[] | null | undefined,
    billingPlan: BillingPlan | null,
    organizationId: string | null | undefined
): string | null {
    const planKey = getCurrentSupportPlanKey(billing, billingPlan, organizationId)
    if (planKey === BillingPlan.Free) {
        return null
    }
    if (planKey === BillingPlan.Paid) {
        return '72 hours'
    }
    if (planKey === 'boost_trial' || planKey === 'scale_trial') {
        return '1 business day'
    }
    const planName = SUPPORT_PLAN_NAMES[planKey]
    return (planName && getResponseTimeFeature(supportPlans, planName)?.note) || '1 business day'
}
