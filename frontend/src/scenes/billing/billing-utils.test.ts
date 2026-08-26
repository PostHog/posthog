import {
    buildSpendTrackingProperties,
    filterSpendUsageTypes,
    getSpendTypeOptions,
    getUsageTypeOptions,
    sanitizeTeamIds,
    teamIdsForUrl,
} from './billing-utils'

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

    it.each([
        ['a valid array', [1, 2, 3], [1, 2, 3]],
        ['a string from an unparsed URL value', '1,2,3', []],
        ['non-numeric members', [1, 'x', 3], [1, 3]],
        ['undefined', undefined, []],
    ])('sanitizeTeamIds accepts %s', (_label, input, expected) => {
        expect(sanitizeTeamIds(input)).toEqual(expected)
    })

    it('drops team_ids from the URL when every project is selected', () => {
        const options = [{ key: '1' }, { key: '2' }, { key: '3' }]
        expect(teamIdsForUrl([1, 2, 3], options)).toEqual([])
        expect(teamIdsForUrl([1, 2], options)).toEqual([1, 2])
    })
})
