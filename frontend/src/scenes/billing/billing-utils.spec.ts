import { dayjs } from 'lib/dayjs'
import tk from 'timekeeper'

import { billingJson } from '~/mocks/fixtures/_billing'
import billingJsonWithFlatFee from '~/mocks/fixtures/_billing_with_flat_fee.json'

import {
    convertAmountToUsage,
    convertLargeNumberToWords,
    convertUsageToAmount,
    getProration,
    projectUsage,
    summarizeUsage,
    updateBillingSearchParams,
} from './billing-utils'

describe('summarizeUsage', () => {
    it('should summarise usage', () => {
        expect(summarizeUsage(0)).toEqual('0')
        expect(summarizeUsage(999)).toEqual('999')
        expect(summarizeUsage(1000)).toEqual('1 thousand')
        expect(summarizeUsage(3345)).toEqual('3.3 thousand')
        expect(summarizeUsage(3600)).toEqual('3.6 thousand')
        expect(summarizeUsage(100000)).toEqual('100 thousand')
        expect(summarizeUsage(999999)).toEqual('1 million')
        expect(summarizeUsage(10000000)).toEqual('10 million')
    })
})

describe('projectUsage', () => {
    beforeEach(() => {
        tk.freeze(new Date('2022-01-01'))
    })
    afterEach(() => {
        tk.reset()
    })
    it('should projectUsage based on the remaining days', () => {
        expect(
            projectUsage(10000, {
                current_period_start: dayjs().add(-100, 'hours'),
                current_period_end: dayjs().add(100, 'hours'),
                interval: 'month',
            })
        ).toEqual(20000)

        expect(
            projectUsage(10000, {
                current_period_start: dayjs().add(-1, 'days'),
                current_period_end: dayjs().add(30, 'days'),
                interval: 'month',
            })
        ).toEqual(310000)
    })

    it('should not return infinity', () => {
        expect(
            projectUsage(10000, {
                current_period_start: dayjs(),
                current_period_end: dayjs().add(100, 'hours'),
                interval: 'month',
            })
        ).toEqual(10000)
    })
})

const amountToUsageMapping = [
    { usage: 0, amount: '0.00' },
    { usage: 1_000_000, amount: '0.00' },
    { usage: 1_500_000, amount: '155.00' },
    { usage: 2_000_000, amount: '310.00' },
    { usage: 6_000_000, amount: '830.00' },
    { usage: 10_000_000, amount: '1350.00' },
    { usage: 230_000_000, amount: '10183.50' },
]

const amountToUsageMappingWithAddons = [
    { usage: 0, amount: '0.00' },
    { usage: 1_000_000, amount: '0.00' },
    { usage: 1_409_086, amount: '155.78' },
    { usage: 1_818_172, amount: '311.56' },
    { usage: 4_888_063, amount: '842.89' },
    { usage: 8_137_188, amount: '1362.75' },
    { usage: 139_090_972, amount: '9914.62' },
]

// 20% discount
const amountToUsageMappingWithPercentDiscount = [
    { usage: 0, amount: '0.00' },
    { usage: 1_000_000, amount: '0.00' },
    { usage: 1_625_000, amount: '155.00' },
    { usage: 2_500_000, amount: '300.00' },
    { usage: 7_500_000, amount: '820.00' },
    { usage: 17_500_000, amount: '1763.80' },
    { usage: 352_500_000, amount: '8947.60' },
]

describe('convertUsageToAmount', () => {
    it.each(amountToUsageMapping)('should convert usage to an amount based on the tiers', (mapping) => {
        if (billingJson.products[0].tiers) {
            expect(convertUsageToAmount(mapping.usage, [billingJson.products[0].tiers])).toEqual(mapping.amount)
        }
    })
})
describe('convertUsageToAmountWithAddons', () => {
    it.each(amountToUsageMappingWithAddons)('should convert usage to an amount based on the tiers', (mapping) => {
        if (billingJson.products[0].tiers) {
            expect(
                convertUsageToAmount(mapping.usage, [
                    billingJson.products[0].tiers,
                    billingJson.products[0].addons[0].tiers || [],
                ])
            ).toEqual(mapping.amount)
        }
    })
})
describe('convertAmountToUsage', () => {
    it.each(amountToUsageMapping)('should convert amount to a usage based on the tiers', (mapping) => {
        if (mapping.usage === 0) {
            // Skip the 0 case as anything below a million is free
            return
        }
        if (billingJson.products[0].tiers) {
            expect(convertAmountToUsage(mapping.amount, [billingJson.products[0].tiers])).toEqual(mapping.usage)
        }
    })
})
describe('convertAmountToUsageWithAddons', () => {
    it.each(amountToUsageMappingWithAddons)('should convert amount to a usage based on the tiers', (mapping) => {
        if (mapping.usage === 0) {
            // Skip the 0 case as anything below a million is free
            return
        }
        if (billingJson.products[0].tiers) {
            expect(
                convertAmountToUsage(mapping.amount, [
                    billingJson.products[0].tiers,
                    billingJson.products[0].addons[0].tiers || [],
                ])
            ).toEqual(mapping.usage)
        }
    })
})
describe('convertUsageToAmountWithPercentDiscount', () => {
    it.each(amountToUsageMappingWithPercentDiscount)(
        'should convert usage to an amount based on the tiers',
        (mapping) => {
            const discountPercent = 20
            if (billingJson.products[0].tiers) {
                expect(convertUsageToAmount(mapping.usage, [billingJson.products[0].tiers], discountPercent)).toEqual(
                    mapping.amount
                )
            }
        }
    )
})

const amountToUsageMappingWithFirstTierFlatFee = [
    { usage: 5_000_000, amount: '200.00' },
    { usage: 10_000_000, amount: '575.00' },
    { usage: 30_000_000, amount: '1725.00' },
]
describe('amountToUsageMappingWithFirstTierFlatFee', () => {
    it.each(amountToUsageMappingWithFirstTierFlatFee)(
        'should convert usage to an amount based on the tiers',
        (mapping) => {
            if (billingJsonWithFlatFee.products[0].tiers) {
                expect(convertUsageToAmount(mapping.usage, [billingJsonWithFlatFee.products[0].tiers])).toEqual(
                    mapping.amount
                )
            }
        }
    )
    it.each(amountToUsageMappingWithFirstTierFlatFee)(
        'should convert amount to a usage based on the tiers',
        (mapping) => {
            if (billingJsonWithFlatFee.products[0].tiers) {
                expect(convertAmountToUsage(mapping.amount, [billingJsonWithFlatFee.products[0].tiers])).toEqual(
                    mapping.usage
                )
            }
        }
    )
})
describe('convertAmountToUsageWithPercentDiscount', () => {
    it.each(amountToUsageMappingWithPercentDiscount)(
        'should convert amount to a usage based on the tiers',
        (mapping) => {
            if (mapping.usage === 0) {
                // Skip the 0 case as anything below a million is free
                return
            }
            if (billingJson.products[0].tiers) {
                const discountPercent = 20
                expect(convertAmountToUsage(mapping.amount, [billingJson.products[0].tiers], discountPercent)).toEqual(
                    mapping.usage
                )
            }
        }
    )
})

describe('convertLargeNumberToWords', () => {
    it('should convert large numbers to words', () => {
        expect(convertLargeNumberToWords(250, null, true, 'survey')).toEqual('First 250 surveys/mo')
        expect(convertLargeNumberToWords(500, 250, true, 'survey')).toEqual('251-500')
        expect(convertLargeNumberToWords(1000, 500, true, 'survey')).toEqual('501-1k')
        expect(convertLargeNumberToWords(10000, 1000, true, 'survey')).toEqual('1-10k')
        expect(convertLargeNumberToWords(10000000, 1000000, true, 'survey')).toEqual('1-10 million')
    })
})

describe('getProration', () => {
    it('should return proration amount and isProrated when all values are provided', () => {
        const result = getProration({
            timeRemainingInSeconds: 15,
            timeTotalInSeconds: 30,
            amountUsd: '100',
            hasActiveSubscription: true,
        })
        expect(result).toEqual({
            isProrated: true,
            prorationAmount: '50.00',
        })
    })

    it('should return 0 proration amount and false isProrated when amountUsd is not provided', () => {
        const result = getProration({
            timeRemainingInSeconds: 15,
            timeTotalInSeconds: 30,
            amountUsd: null,
            hasActiveSubscription: true,
        })
        expect(result).toEqual({
            isProrated: false,
            prorationAmount: '0.00',
        })
    })

    it('should return proration amount and false isProrated when subscription is not active', () => {
        const result = getProration({
            timeRemainingInSeconds: 15,
            timeTotalInSeconds: 30,
            amountUsd: '100',
            hasActiveSubscription: false,
        })
        expect(result).toEqual({
            isProrated: false,
            prorationAmount: '50.00',
        })
    })

    it('should handle zero timeTotalInSeconds gracefully', () => {
        const result = getProration({
            timeRemainingInSeconds: 15,
            timeTotalInSeconds: 0,
            amountUsd: '100',
            hasActiveSubscription: true,
        })
        expect(result).toEqual({
            isProrated: false,
            prorationAmount: '0.00',
        })
    })

    it('should handle zero timeRemainingInSeconds gracefully', () => {
        const result = getProration({
            timeRemainingInSeconds: 0,
            timeTotalInSeconds: 30,
            amountUsd: '100',
            hasActiveSubscription: true,
        })
        expect(result).toEqual({
            isProrated: true,
            prorationAmount: '0.00',
        })
    })

    it('should return 0 proration amount and false isProrated when amountUsd is an empty string', () => {
        const result = getProration({
            timeRemainingInSeconds: 15,
            timeTotalInSeconds: 30,
            amountUsd: '',
            hasActiveSubscription: true,
        })
        expect(result).toEqual({
            isProrated: false,
            prorationAmount: '0.00',
        })
    })
})

describe('updateBillingSearchParams', () => {
    it('should JSON stringify arrays to ensure proper URL parameter format', () => {
        const searchParams: Record<string, any> = {}

        updateBillingSearchParams(searchParams, 'breakdowns', ['type', 'team'], ['type'])
        updateBillingSearchParams(searchParams, 'usage_types', ['product_analytics', 'session_replay'], [])
        updateBillingSearchParams(searchParams, 'team_ids', [1, 2, 3], [])

        expect(searchParams.breakdowns).toBe('["type","team"]')
        expect(searchParams.usage_types).toBe('["product_analytics","session_replay"]')
        expect(searchParams.team_ids).toBe('[1,2,3]')
    })

    it('should not modify non-array values', () => {
        const searchParams: Record<string, any> = {}

        updateBillingSearchParams(searchParams, 'interval', 'day', 'week')
        updateBillingSearchParams(searchParams, 'date_from', '2024-01-01', '')
        updateBillingSearchParams(searchParams, 'date_to', '2024-12-31', '')

        expect(searchParams.interval).toBe('day')
        expect(searchParams.date_from).toBe('2024-01-01')
        expect(searchParams.date_to).toBe('2024-12-31')
    })

    it('should delete parameters when value equals defaultValue', () => {
        const searchParams: Record<string, any> = {
            breakdowns: '["type","team"]',
            interval: 'day',
        }

        updateBillingSearchParams(searchParams, 'breakdowns', ['type', 'team'], ['type', 'team'])
        updateBillingSearchParams(searchParams, 'interval', 'day', 'day')

        expect(searchParams.breakdowns).toBeUndefined()
        expect(searchParams.interval).toBeUndefined()
    })

    it('should handle mixed array and non-array values correctly', () => {
        const searchParams: Record<string, any> = {}

        updateBillingSearchParams(searchParams, 'breakdowns', ['type', 'team'], ['type'])
        updateBillingSearchParams(searchParams, 'interval', 'day', 'week')
        updateBillingSearchParams(searchParams, 'usage_types', ['product_analytics'], [])

        expect(searchParams.breakdowns).toBe('["type","team"]')
        expect(searchParams.interval).toBe('day')
        expect(searchParams.usage_types).toBe('["product_analytics"]')
    })

    it('should handle empty arrays correctly', () => {
        const searchParams: Record<string, any> = {}

        updateBillingSearchParams(searchParams, 'breakdowns', [], ['type'])

        expect(searchParams.breakdowns).toBe('[]')
    })

    it('should produce correct URL parameters for arrays', () => {
        const searchParams: Record<string, any> = {}

        updateBillingSearchParams(searchParams, 'breakdowns', ['type', 'team'], ['type'])

        const urlParams = new URLSearchParams()
        Object.entries(searchParams).forEach(([key, value]) => {
            urlParams.set(key, value)
        })

        const url = `https://us.posthog.com/project/1/web?${urlParams.toString()}`

        expect(url).toContain('breakdowns=%5B%22type%22%2C%22team%22%5D')

        expect(searchParams.breakdowns).toBe('["type","team"]')

        const decodedParams = new URLSearchParams(url.split('?')[1])
        const decodedBreakdowns = JSON.parse(decodeURIComponent(decodedParams.get('breakdowns')!))
        expect(decodedBreakdowns).toEqual(['type', 'team'])
    })

    it('should handle multiple array parameters in URL correctly', () => {
        const searchParams: Record<string, any> = {}

        updateBillingSearchParams(searchParams, 'usage_types', ['product_analytics', 'session_replay'], [])
        updateBillingSearchParams(searchParams, 'team_ids', [1, 2, 3], [])
        updateBillingSearchParams(searchParams, 'breakdowns', ['type', 'team'], ['type'])

        const urlParams = new URLSearchParams()
        Object.entries(searchParams).forEach(([key, value]) => {
            urlParams.set(key, value)
        })

        const url = `https://us.posthog.com/project/1/web?${urlParams.toString()}`

        expect(url).toContain('usage_types=%5B%22product_analytics%22%2C%22session_replay%22%5D')
        expect(url).toContain('team_ids=%5B1%2C2%2C3%5D')
        expect(url).toContain('breakdowns=%5B%22type%22%2C%22team%22%5D')

        const decodedParams = new URLSearchParams(url.split('?')[1])
        expect(JSON.parse(decodeURIComponent(decodedParams.get('usage_types')!))).toEqual([
            'product_analytics',
            'session_replay',
        ])
        expect(JSON.parse(decodeURIComponent(decodedParams.get('team_ids')!))).toEqual([1, 2, 3])
        expect(JSON.parse(decodeURIComponent(decodedParams.get('breakdowns')!))).toEqual(['type', 'team'])
    })
})
