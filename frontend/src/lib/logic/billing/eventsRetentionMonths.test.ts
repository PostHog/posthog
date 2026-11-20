import { AvailableFeature, BillingPlanType } from '~/types'

import { keepsEventsRetentionMonths, longestEventsRetentionMonths } from './eventsRetentionMonths'

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

describe('keepsEventsRetentionMonths', () => {
    it.each([
        ['two packages with the same period', planKeeping(3, 'years'), planKeeping(3, 'years'), true],
        ['a package with a shorter period', planKeeping(5, 'years'), planKeeping(3, 'years'), false],
        ['plans without events retention', { features: [] }, { features: [] }, false],
    ])('compares %s', (_, currentPlan, targetPlan, keeps) => {
        expect(keepsEventsRetentionMonths(currentPlan as BillingPlanType, targetPlan as BillingPlanType)).toBe(keeps)
    })
})
