import { AvailableFeature, BillingPlan, BillingPlanType, BillingType } from '~/types'

import { KNOWN_ENTERPRISE_ORG_IDS, SupportPlanContext, getSupportResponseTime } from './supportResponseTime'

const supportPlan = (name: string, note: string): BillingPlanType =>
    ({
        name,
        features: [{ key: AvailableFeature.SUPPORT_RESPONSE_TIME, name: 'Support response time', note }],
    }) as unknown as BillingPlanType

const trial = (target: 'boost' | 'scale' | 'enterprise', status: 'active' | 'expired' = 'active'): BillingType =>
    ({ trial: { status, target } }) as unknown as BillingType

describe('getSupportResponseTime', () => {
    const supportPlans = [
        supportPlan('Boost', '48 hours'),
        supportPlan('Scale', '24 hours'),
        supportPlan('Enterprise', '8 hours'),
    ]

    it.each<[string, SupportPlanContext, string | null]>([
        ['free plans get no response time', { billingPlan: BillingPlan.Free, supportPlans }, null],
        ['nothing when billing has not loaded', {}, null],
        ['pay-as-you-go gets its fixed target', { billingPlan: BillingPlan.Paid, supportPlans }, '72 hours'],
        ['boost uses the time published by billing', { billingPlan: BillingPlan.Boost, supportPlans }, '48 hours'],
        ['scale uses the time published by billing', { billingPlan: BillingPlan.Scale, supportPlans }, '24 hours'],
        [
            'enterprise uses the time published by billing',
            { billingPlan: BillingPlan.Enterprise, supportPlans },
            '8 hours',
        ],
        ['plans billing publishes no time for get none', { billingPlan: BillingPlan.Teams, supportPlans }, null],
        [
            'paid plan without support plans loaded still gets the fixed target',
            { billingPlan: BillingPlan.Paid },
            '72 hours',
        ],
        ['boost without support plans loaded gets none', { billingPlan: BillingPlan.Boost }, null],
        [
            'a published value that is not a duration is not promised',
            { billingPlan: BillingPlan.Scale, supportPlans: [supportPlan('Scale', 'Priority support')] },
            null,
        ],
        [
            'active boost trial gets none',
            { billingPlan: BillingPlan.Free, billing: trial('boost'), supportPlans },
            null,
        ],
        [
            'active scale trial gets none',
            { billingPlan: BillingPlan.Paid, billing: trial('scale'), supportPlans },
            null,
        ],
        [
            'active enterprise trial gets none',
            { billingPlan: BillingPlan.Paid, billing: trial('enterprise'), supportPlans },
            null,
        ],
        [
            'expired trial falls back to the actual plan',
            { billingPlan: BillingPlan.Paid, billing: trial('scale', 'expired'), supportPlans },
            '72 hours',
        ],
        [
            'known enterprise org uses the enterprise time',
            { organizationId: KNOWN_ENTERPRISE_ORG_IDS[0], supportPlans },
            '8 hours',
        ],
    ])('%s', (_name, context, expected) => {
        expect(getSupportResponseTime(context)).toBe(expected)
    })
})
