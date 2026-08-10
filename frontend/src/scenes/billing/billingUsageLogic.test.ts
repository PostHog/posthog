import { BillingUsageResponseBreakdownType, convertDesktopUsageSeries } from './billingUsageLogic'

const series = (label: string, data: number[]) => ({
    id: 1,
    label,
    data,
    dates: ['2026-08-01'],
    breakdown_type: BillingUsageResponseBreakdownType.TYPE,
    breakdown_value: label,
})

describe('convertDesktopUsageSeries', () => {
    it.each([
        ['PostHog Desktop token credits', 1234, 12.34, 'PostHog Desktop token spend (USD)'],
        ['Sandbox compute credits', 266, 2.66, 'Cloud compute spend (USD)'],
        ['Sandbox compute CPU millicore-seconds', 1500, 1.5, 'Cloud compute CPU (core-seconds)'],
        ['Sandbox compute memory MiB-seconds', 4608, 4.5, 'Cloud compute memory (GiB-seconds)'],
    ])('converts %s without changing missing points', (label, input, output, expectedLabel) => {
        expect(convertDesktopUsageSeries(series(label, [input]))).toMatchObject({
            label: expectedLabel,
            data: [output],
        })
    })

    it('leaves unrelated usage series unchanged', () => {
        const input = series('Events', [10])
        expect(convertDesktopUsageSeries(input)).toBe(input)
    })
})
