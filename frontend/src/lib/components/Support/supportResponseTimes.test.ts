import { AvailableFeature, BillingPlan, BillingPlanType, BillingType } from '~/types'

import { KNOWN_ENTERPRISE_ORG_IDS, getSupportResponseTime } from './supportResponseTimes'

describe('supportResponseTimes', () => {
    const supportPlansWithNotes = (notes: Record<string, string>): BillingPlanType[] =>
        Object.entries(notes).map(
            ([name, note]) =>
                ({
                    name,
                    features: [{ key: AvailableFeature.SUPPORT_RESPONSE_TIME, name: 'Support response time', note }],
                }) as unknown as BillingPlanType
        )

    const activeTrial = (target: 'boost' | 'scale' | 'enterprise'): BillingType =>
        ({ trial: { status: 'active', target } }) as BillingType

    test.each([
        ['free plan', null, [], null, undefined, null],
        ['paid plan', null, [], BillingPlan.Paid, undefined, '72 hours'],
        [
            'boost plan with billing note',
            null,
            supportPlansWithNotes({ Boost: '48 hours' }),
            BillingPlan.Boost,
            undefined,
            '48 hours',
        ],
        ['boost plan without billing note', null, [], BillingPlan.Boost, undefined, '1 business day'],
        [
            'scale plan with billing note',
            null,
            supportPlansWithNotes({ Scale: '24 hours' }),
            BillingPlan.Scale,
            undefined,
            '24 hours',
        ],
        [
            'enterprise plan with billing note',
            null,
            supportPlansWithNotes({ Enterprise: '8 hours' }),
            BillingPlan.Enterprise,
            undefined,
            '8 hours',
        ],
        ['boost trial on free plan', activeTrial('boost'), [], BillingPlan.Free, undefined, '1 business day'],
        ['scale trial on free plan', activeTrial('scale'), [], BillingPlan.Free, undefined, '1 business day'],
        [
            'enterprise trial resolves to the enterprise note',
            activeTrial('enterprise'),
            supportPlansWithNotes({ Enterprise: '8 hours' }),
            BillingPlan.Free,
            undefined,
            '8 hours',
        ],
        [
            'known enterprise org on any plan',
            null,
            supportPlansWithNotes({ Enterprise: '8 hours' }),
            BillingPlan.Free,
            KNOWN_ENTERPRISE_ORG_IDS[0],
            '8 hours',
        ],
    ] as [string, BillingType | null, BillingPlanType[], BillingPlan | null, string | undefined, string | null][])(
        '%s',
        (_name, billing, supportPlans, billingPlan, organizationId, expected) => {
            expect(getSupportResponseTime(billing, supportPlans, billingPlan, organizationId)).toBe(expected)
        }
    )
})
