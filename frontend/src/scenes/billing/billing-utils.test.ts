import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import {
    buildSpendTrackingProperties,
    filterSpendUsageTypes,
    getSpendTypeOptions,
    getUsageTypeOptions,
} from './billing-utils'

describe('getUsageTypeOptions', () => {
    it.each<[string, FeatureFlagsSet, boolean]>([
        ['on', { [FEATURE_FLAGS.REPLAY_VISION]: true }, true],
        ['off', { [FEATURE_FLAGS.REPLAY_VISION]: false }, false],
        ['missing', {}, false],
    ])(
        'shows replay vision credits only when the replay-vision flag is on (flag %s)',
        (_name, featureFlags, visible) => {
            const options = getUsageTypeOptions(featureFlags)
            expect(options.some((opt) => opt.key === 'replay_vision_credits_used_in_period')).toBe(visible)
            // the gate never affects other usage types
            expect(options.some((opt) => opt.key === 'event_count_in_period')).toBe(true)
        }
    )

    it('includes informational Desktop component metrics in Usage but not Spend', () => {
        const usageOptions = getUsageTypeOptions({})
        const spendOptions = getSpendTypeOptions({})
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

    it.each<[string, FeatureFlagsSet]>([
        ['on', { [FEATURE_FLAGS.REPLAY_VISION]: true }],
        ['off', { [FEATURE_FLAGS.REPLAY_VISION]: false }],
    ])(
        'reports only selectable Spend types in interaction analytics when Replay Vision is %s',
        (_name, featureFlags) => {
            const properties = buildSpendTrackingProperties(
                'filters_changed',
                {
                    filters: {},
                    dateFrom: '2026-08-01',
                    dateTo: '2026-08-06',
                    excludeEmptySeries: false,
                    teamOptions: [],
                },
                featureFlags
            )

            expect(properties.usage_types_total).toBe(getSpendTypeOptions(featureFlags).length)
        }
    )

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
