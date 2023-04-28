import { convertAmountToUsage, convertUsageToAmount, projectUsage, summarizeUsage } from './billing-utils'
import tk from 'timekeeper'
import { dayjs } from 'lib/dayjs'
import billingJson from '~/mocks/fixtures/_billing_v2.json'

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
    { usage: 1_500_000, amount: '225.00' },
    { usage: 2_000_000, amount: '450.00' },
    { usage: 6_000_000, amount: '1350.00' },
    { usage: 10_000_000, amount: '2250.00' },
    { usage: 230_000_000, amount: '12250.00' },
]

// 20% discount
const amountToUsageMappingWithPercentDiscount = [
    { usage: 0, amount: '0.00' },
    { usage: 1_000_000, amount: '0.00' },
    { usage: 1_600_000, amount: '225.00' }, // $270 worth of units
    { usage: 2_400_000, amount: '450.00' }, // $540 worth of units
    { usage: 7_200_000, amount: '1350.00' }, // $1620 worth of units
    { usage: 16_000_000, amount: '2250.00' }, // $2700 worth of units
    { usage: 328_000_000, amount: '12250.00' }, // $14700 worth of units
]

describe('convertUsageToAmount', () => {
    it.each(amountToUsageMapping)('should convert usage to an amount based on the tiers', (mapping) => {
        expect(convertUsageToAmount(mapping.usage, billingJson.products[0].tiers)).toEqual(mapping.amount)
    })
})
describe('convertAmountToUsage', () => {
    it.each(amountToUsageMapping)('should convert amount to a usage based on the tiers', (mapping) => {
        if (mapping.usage === 0) {
            // Skip the 0 case as anything below a million is free
            return
        }
        expect(convertAmountToUsage(mapping.amount, billingJson.products[0].tiers)).toEqual(mapping.usage)
    })
})
describe('convertUsageToAmountWithPercentDiscount', () => {
    it.each(amountToUsageMappingWithPercentDiscount)(
        'should convert usage to an amount based on the tiers',
        (mapping) => {
            expect(
                convertUsageToAmount(mapping.usage, billingJson.products[0].tiers, billingJson.discount_percent)
            ).toEqual(mapping.amount)
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
            expect(
                convertAmountToUsage(mapping.amount, billingJson.products[0].tiers, billingJson.discount_percent)
            ).toEqual(mapping.usage)
        }
    )
})
