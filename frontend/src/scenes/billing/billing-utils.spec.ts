import { dayjs } from 'lib/dayjs'
import tk from 'timekeeper'

import { billingJson } from '~/mocks/fixtures/_billing_v2'
import billingJsonWithFlatFee from '~/mocks/fixtures/_billing_v2_with_flat_fee.json'

import {
    convertAmountToUsage,
    convertLargeNumberToWords,
    convertUsageToAmount,
    projectUsage,
    summarizeUsage,
} from './billing-utils'

describe('summarizeUsage', () => {
    it('should summarise usage', () => {
        expect(summarizeUsage(0)).toEqual('0')
        expect(summarizeUsage(999)).toEqual('999')
        expect(summarizeUsage(1000)).toEqual('1 thousand')
        expect(summarizeUsage(3345)).toEqual('3 thousand')
        expect(summarizeUsage(3600)).toEqual('4 thousand')
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
