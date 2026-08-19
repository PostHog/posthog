import { initKeaTests } from '~/test/init'

import {
    BillingUsageResponse,
    BillingUsageResponseBreakdownType,
    billingUsageLogic,
    convertDesktopUsageSeries,
} from './billingUsageLogic'

const series = (label: string, usageType: string, data: number[]): BillingUsageResponse['results'][number] => ({
    id: 1,
    label,
    data,
    dates: ['2026-08-01'],
    breakdown_type: BillingUsageResponseBreakdownType.TYPE,
    breakdown_value: usageType,
})

const response = (results: BillingUsageResponse['results']): BillingUsageResponse => ({
    status: 'ok',
    type: 'timeseries',
    customer_id: 'cus_test',
    results,
})

describe('convertDesktopUsageSeries', () => {
    it.each([
        [
            'PostHog Desktop token credits',
            'posthog_code_token_credits_used_in_period',
            1234,
            12.34,
            'PostHog Desktop token spend (USD)',
        ],
        ['Sandbox compute credits', 'sandbox_compute_credits_used_in_period', 266, 2.66, 'Cloud compute spend (USD)'],
        [
            'Sandbox compute CPU millicore-seconds',
            'sandbox_compute_cpu_millicore_seconds_in_period',
            1500,
            1.5,
            'Cloud compute CPU (core-seconds)',
        ],
        [
            'Sandbox compute memory MiB-seconds',
            'sandbox_compute_memory_mib_seconds_in_period',
            4608,
            4.5,
            'Cloud compute memory (GiB-seconds)',
        ],
    ])('converts %s without changing missing points', (label, usageType, input, output, expectedLabel) => {
        expect(convertDesktopUsageSeries(series(label, usageType, [input]))).toMatchObject({
            label: expectedLabel,
            data: [output],
        })
    })

    it('leaves unrelated usage series unchanged', () => {
        const input = series('Events', 'events', [10])
        expect(convertDesktopUsageSeries(input)).toBe(input)
    })

    it('converts a project breakdown and preserves its label', () => {
        const input = {
            ...series('my-project::PostHog Desktop token credits', 'posthog_code_token_credits_used_in_period', [1234]),
            breakdown_type: BillingUsageResponseBreakdownType.MULTIPLE,
            breakdown_value: ['posthog_code_token_credits_used_in_period', 'my-project'],
        }

        expect(convertDesktopUsageSeries(input)).toMatchObject({
            label: 'my-project::PostHog Desktop token spend (USD)',
            data: [12.34],
        })
    })
})

describe('billingUsageLogic series selection', () => {
    beforeEach(() => {
        initKeaTests()
        billingUsageLogic.mount()
    })

    it('keeps a hidden series on the same product after a reload reorders the positional ids', () => {
        // First range: three products, ids assigned by position.
        billingUsageLogic.actions.loadBillingUsageSuccess(
            response([
                { ...series('Events', 'events', [10]), id: 0 },
                { ...series('Recordings', 'recordings', [5]), id: 1 },
                { ...series('Feature flags', 'feature_flags', [3]), id: 2 },
            ])
        )

        billingUsageLogic.actions.toggleSeries('recordings')
        expect(billingUsageLogic.values.finalHiddenSeries).toEqual(['recordings'])

        // Second range: 'events' has no usage and drops out, so 'recordings' now sits at id 0.
        // A positional selection would follow the id and hide the wrong product.
        billingUsageLogic.actions.loadBillingUsageSuccess(
            response([
                { ...series('Recordings', 'recordings', [7]), id: 0 },
                { ...series('Feature flags', 'feature_flags', [4]), id: 1 },
            ])
        )

        expect(billingUsageLogic.values.finalHiddenSeries).toEqual(['recordings'])
    })
})
