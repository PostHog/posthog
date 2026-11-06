import { AvailableFeature, BillingPlanType } from '~/types'

import { longestEventsRetentionMonths } from './eventsRetentionMonths'

const planKeeping = (limit: number, unit: string): BillingPlanType =>
    ({
        features: [{ key: AvailableFeature.PRODUCT_ANALYTICS_DATA_RETENTION, name: 'Data retention', limit, unit }],
    }) as BillingPlanType

describe('longestEventsRetentionMonths', () => {
    it.each([
        ['a year in months', [planKeeping(1, 'year')], 12],
        ['the longer of two plans', [planKeeping(3, 'months'), planKeeping(2, 'years')], 24],
        ['no plans', [null, undefined], null],
        ['a plan without events retention', [{ features: [] } as unknown as BillingPlanType], null],
    ])('counts %s', (_, plans, months) => {
        expect(longestEventsRetentionMonths(plans)).toBe(months)
    })
})
