import { AvailableFeature, BillingFeatureType, BillingPlan, BillingPlanType, BillingType } from '~/types'

export const PAY_AS_YOU_GO_RESPONSE_TIME = '72 hours'
export const DEFAULT_PAID_RESPONSE_TIME = '1 business day'

export const KNOWN_ENTERPRISE_ORG_IDS = ['018713f3-8d56-0000-32fa-75ce97e6662f']

export type CurrentSupportPlan = BillingPlan | 'boost_trial' | 'scale_trial'

export interface SupportPlanContext {
    billing?: BillingType | null
    billingPlan?: BillingPlan | null
    supportPlans?: BillingPlanType[] | null
    organizationId?: string | null
}

export function getCurrentSupportPlan({
    billing,
    billingPlan,
    organizationId,
}: SupportPlanContext): CurrentSupportPlan {
    const activeTrialTarget = billing?.trial?.status === 'active' ? billing.trial.target : null

    if (
        KNOWN_ENTERPRISE_ORG_IDS.includes(organizationId || '') ||
        activeTrialTarget === 'enterprise' ||
        billingPlan === BillingPlan.Enterprise
    ) {
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

export function getSupportResponseTimeFeature(
    supportPlans: BillingPlanType[] | null | undefined,
    planName: string
): BillingFeatureType | undefined {
    return supportPlans
        ?.find((plan) => plan.name?.includes(planName))
        ?.features?.find((feature) => feature.key === AvailableFeature.SUPPORT_RESPONSE_TIME)
}

/**
 * Target support response time for the current plan, using exactly the values the help panel's
 * response times table shows: the time billing publishes for the plan, or the fixed pay-as-you-go
 * target. Returns null for free plans, active trials, and plans without a published duration, so
 * callers can leave the promise out entirely rather than fall back to a made-up one.
 */
export function getSupportResponseTime(context: SupportPlanContext): string | null {
    const activeTrialTarget = context.billing?.trial?.status === 'active' ? context.billing.trial.target : null
    if (activeTrialTarget === 'boost' || activeTrialTarget === 'scale' || activeTrialTarget === 'enterprise') {
        return null
    }

    const fromBilling = (planName: string): string | null => {
        const note = getSupportResponseTimeFeature(context.supportPlans, planName)?.note?.trim()
        return note && /^\d/.test(note) ? note : null
    }

    switch (getCurrentSupportPlan(context)) {
        case BillingPlan.Enterprise:
            return fromBilling('Enterprise')
        case BillingPlan.Scale:
            return fromBilling('Scale')
        case BillingPlan.Teams:
            return fromBilling('Teams')
        case BillingPlan.Boost:
            return fromBilling('Boost')
        case 'scale_trial':
        case 'boost_trial':
            return null
        case BillingPlan.Paid:
            return PAY_AS_YOU_GO_RESPONSE_TIME
        case BillingPlan.Free:
            return null
    }
}

export interface SupportPlanRow {
    key: string
    name: string
    isCurrentPlan: boolean
    /** Null when billing lists the plan's response time feature without a note. */
    responseTime: string | null
    /** Where a plan without a response time points instead, e.g. the community forum. */
    link?: string
    legacy?: boolean
}

/** The rows of the help panel's support response times table, one per plan, with the current plan marked. */
export function getSupportPlanRows(context: SupportPlanContext): SupportPlanRow[] {
    const currentPlan = getCurrentSupportPlan(context)
    const paidResponseTime = (planName: string): string | null => {
        const feature = getSupportResponseTimeFeature(context.supportPlans, planName)
        return feature ? (feature.note ?? null) : DEFAULT_PAID_RESPONSE_TIME
    }

    return [
        {
            key: BillingPlan.Free,
            name: 'Free',
            isCurrentPlan: currentPlan === BillingPlan.Free,
            responseTime: 'Community support only',
            link: 'https://posthog.com/questions',
        },
        {
            key: BillingPlan.Paid,
            name: 'Pay-as-you-go',
            isCurrentPlan: currentPlan === BillingPlan.Paid,
            responseTime: PAY_AS_YOU_GO_RESPONSE_TIME,
        },
        {
            key: BillingPlan.Boost,
            name: 'Boost',
            isCurrentPlan: currentPlan === BillingPlan.Boost,
            responseTime: paidResponseTime('Boost'),
        },
        ...(context.billingPlan === BillingPlan.Teams
            ? [
                  {
                      key: BillingPlan.Teams,
                      name: 'Teams',
                      isCurrentPlan: currentPlan === BillingPlan.Teams,
                      responseTime: paidResponseTime('Teams'),
                      legacy: true,
                  },
              ]
            : []),
        {
            key: BillingPlan.Scale,
            name: 'Scale',
            isCurrentPlan: currentPlan === BillingPlan.Scale,
            responseTime: paidResponseTime('Scale'),
        },
        {
            key: BillingPlan.Enterprise,
            name: 'Enterprise',
            isCurrentPlan: currentPlan === BillingPlan.Enterprise,
            responseTime: paidResponseTime('Enterprise'),
        },
    ]
}
