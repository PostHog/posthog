import { dayjs } from 'lib/dayjs'

import {
    buildSpendTrackingProperties,
    filterSpendUsageTypes,
    getSpendTypeOptions,
    getUsageTypeOptions,
    resolveBillingChartDates,
} from './billing-utils'

describe('resolveBillingChartDates', () => {
    const inRange = ['2026-08-01', '2026-08-02', '2026-08-03']
    const stale = ['2024-01-01', '2024-01-02', '2024-01-03']

    it('skips a stale first series and labels the chart from a series inside the range', () => {
        const series = [{ dates: stale }, { dates: inRange }]
        expect(resolveBillingChartDates(series, '2026-08-01', '2026-08-03')).toEqual(inRange)
    })

    it('keeps the first series when every series shares the same in-range dates', () => {
        const series = [{ dates: inRange }, { dates: inRange }]
        expect(resolveBillingChartDates(series, '2026-08-01', '2026-08-03')).toEqual(inRange)
    })

    it('rejects a longer partly-overlapping stale series in favor of one fully inside the range', () => {
        // A stale series can span years yet still touch the requested range at one end. Ranking by
        // length alone would let that longer array label the chart, even when results[0] already
        // holds the correct exact-range array, so only fully-in-range arrays win.
        const stalePartial = ['2025-06-01', '2025-07-01', '2025-08-01', '2026-08-01']
        const series = [{ dates: inRange }, { dates: stalePartial }]
        expect(resolveBillingChartDates(series, '2026-08-01', '2026-08-03')).toEqual(inRange)
    })

    it('falls back to the longest array when no series overlaps the range', () => {
        const series = [{ dates: ['2024-01-01'] }, { dates: stale }]
        expect(resolveBillingChartDates(series, '2026-08-01', '2026-08-03')).toEqual(stale)
    })

    it('resolves a relative preset so a stale longer series is still rejected', () => {
        // The picker stores relative strings like "-30d"; dayjs cannot parse them directly, so the
        // range check must resolve them first or it fails open and the longer stale array wins.
        const recent = [
            dayjs().subtract(2, 'day').format('YYYY-MM-DD'),
            dayjs().subtract(1, 'day').format('YYYY-MM-DD'),
        ]
        const series = [{ dates: stale }, { dates: recent }]
        expect(resolveBillingChartDates(series, '-30d', '-1d')).toEqual(recent)
    })
})

describe('getUsageTypeOptions', () => {
    it('includes informational Desktop component metrics in Usage but not Spend', () => {
        const usageOptions = getUsageTypeOptions()
        const spendOptions = getSpendTypeOptions()
        const componentTypes = [
            'posthog_code_token_credits_used_in_period',
            'sandbox_compute_credits_used_in_period',
            'sandbox_compute_cpu_millicore_seconds_in_period',
            'sandbox_compute_memory_mib_seconds_in_period',
        ]

        for (const usageType of componentTypes) {
            expect(usageOptions.some((option) => option.key === usageType)).toBe(true)
            expect(spendOptions.some((option) => option.key === usageType)).toBe(false)
        }
    })

    it('reports only selectable Spend types in interaction analytics', () => {
        const properties = buildSpendTrackingProperties('filters_changed', {
            filters: {},
            dateFrom: '2026-08-01',
            dateTo: '2026-08-06',
            excludeEmptySeries: false,
            teamOptions: [],
        })

        expect(properties.usage_types_total).toBe(getSpendTypeOptions().length)
    })

    it('removes Usage-only types when switching to Spend', () => {
        expect(
            filterSpendUsageTypes([
                'posthog_code_token_credits_used_in_period',
                'sandbox_compute_credits_used_in_period',
                'event_count_in_period',
            ])
        ).toEqual(['event_count_in_period'])
        expect(filterSpendUsageTypes(['sandbox_compute_cpu_millicore_seconds_in_period'])).toEqual([])
    })
})
