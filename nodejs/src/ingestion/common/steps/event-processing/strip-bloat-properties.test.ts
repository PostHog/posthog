import {
    droppedBloatPropertyCounter,
    featureFlagCalledStripOutcomeCounter,
    strippedFeatureFlagCalledPropertyCounter,
} from '~/ingestion/common/metrics'

import {
    BLOAT_PROPERTIES,
    FEATURE_FLAG_CALLED_KEEP,
    stripBloatProperties,
    stripFeatureFlagCalledProperties,
} from './strip-bloat-properties'

jest.mock('~/ingestion/common/metrics', () => ({
    droppedBloatPropertyCounter: {
        labels: jest.fn().mockReturnValue({ inc: jest.fn() }),
    },
    strippedFeatureFlagCalledPropertyCounter: {
        inc: jest.fn(),
    },
    featureFlagCalledStripOutcomeCounter: {
        labels: jest.fn().mockReturnValue({ inc: jest.fn() }),
    },
}))

const mockBloatLabels = jest.mocked(droppedBloatPropertyCounter.labels)
const mockFlagInc = jest.mocked(strippedFeatureFlagCalledPropertyCounter.inc)
const mockOutcomeLabels = jest.mocked(featureFlagCalledStripOutcomeCounter.labels)

describe('stripBloatProperties', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it.each([...BLOAT_PROPERTIES])('deletes %s and increments the counter for that label', (bloatKey) => {
        const properties: Record<string, any> = { [bloatKey]: { heavy: 'cache-blob' }, other: 'kept' }

        stripBloatProperties(properties)

        expect(properties).not.toHaveProperty(bloatKey)
        expect(properties).toEqual({ other: 'kept' })
        expect(mockBloatLabels).toHaveBeenCalledTimes(1)
        expect(mockBloatLabels).toHaveBeenCalledWith(bloatKey)
    })

    it('strips every bloat property present and increments the counter once per stripped key', () => {
        const properties = Object.fromEntries([...BLOAT_PROPERTIES].map((key) => [key, 'v']))
        properties.other = 'kept'

        stripBloatProperties(properties)

        expect(properties).toEqual({ other: 'kept' })
        expect(mockBloatLabels).toHaveBeenCalledTimes(BLOAT_PROPERTIES.size)
        for (const key of BLOAT_PROPERTIES) {
            expect(mockBloatLabels).toHaveBeenCalledWith(key)
        }
    })

    it('does not increment the counter when no bloat properties are present', () => {
        const properties = { other: 'kept', another: 'also-kept' }

        stripBloatProperties(properties)

        expect(properties).toEqual({ other: 'kept', another: 'also-kept' })
        expect(mockBloatLabels).not.toHaveBeenCalled()
    })

    it('only strips exact matches, not substring matches', () => {
        const properties = {
            ph_product_tours_foo: 'kept',
            my_ph_product_tours: 'kept',
            $product_tours_activated_at: 'kept',
            my_$override_feature_flag_payloads: 'kept',
        }

        stripBloatProperties(properties)

        expect(properties).toEqual({
            ph_product_tours_foo: 'kept',
            my_ph_product_tours: 'kept',
            $product_tours_activated_at: 'kept',
            my_$override_feature_flag_payloads: 'kept',
        })
        expect(mockBloatLabels).not.toHaveBeenCalled()
    })
})

describe('stripFeatureFlagCalledProperties', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it.each([
        '$feature_flag',
        '$feature_flag_response',
        '$feature_flag_id',
        '$feature_flag_version',
        '$feature_flag_request_id',
        '$set',
        '$groups',
        '$group_0',
        '$group_1',
        '$group_2',
        '$group_3',
        '$group_4',
        '$lib',
        '$lib_version',
    ])('keeps business-critical whitelist key %s pinned in FEATURE_FLAG_CALLED_KEEP', (key) => {
        expect(FEATURE_FLAG_CALLED_KEEP.has(key)).toBe(true)
    })

    it.each([...FEATURE_FLAG_CALLED_KEEP])('preserves whitelisted key %s', (key) => {
        const properties: Record<string, any> = { [key]: 'value' }

        stripFeatureFlagCalledProperties(properties)

        expect(properties).toEqual({ [key]: 'value' })
        expect(mockFlagInc).not.toHaveBeenCalled()
    })

    it.each(['$feature/my-flag', '$feature/another-flag', '$feature/flag-with-many-dashes-in-name', '$feature/'])(
        'preserves $feature/ prefixed key %s',
        (key) => {
            const properties: Record<string, any> = { [key]: 'variant-a' }

            stripFeatureFlagCalledProperties(properties)

            expect(properties).toEqual({ [key]: 'variant-a' })
            expect(mockFlagInc).not.toHaveBeenCalled()
        }
    )

    it.each([
        '$initial_current_url',
        '$initial_referrer',
        '$initial_utm_source',
        '$initial_os',
        '$initial_geoip_country_code',
        '$session_entry_url',
        '$session_entry_utm_campaign',
        '$session_entry_referring_domain',
    ])('preserves first-touch / session-entry prefixed key %s', (key) => {
        const properties: Record<string, any> = { [key]: 'value' }

        stripFeatureFlagCalledProperties(properties)

        expect(properties).toEqual({ [key]: 'value' })
        expect(mockFlagInc).not.toHaveBeenCalled()
    })

    it.each([
        'utm_source',
        '$referrer',
        '$referring_domain',
        '$raw_user_agent',
        '$os_name',
        '$device_manufacturer',
        '$channel_type',
        '$user_id',
        '$active_feature_flags',
    ])('preserves standard PostHog auto-captured property %s', (key) => {
        const properties: Record<string, any> = { [key]: 'value' }

        stripFeatureFlagCalledProperties(properties)

        expect(properties).toEqual({ [key]: 'value' })
        expect(mockFlagInc).not.toHaveBeenCalled()
    })

    it.each(['environment', 'platform', 'amount', 'plan', 'revenue', 'variant', 'random_key'])(
        'strips non-whitelisted key %s and increments the counter',
        (key) => {
            const properties: Record<string, any> = { [key]: 'leaked', $feature_flag: 'kept' }

            stripFeatureFlagCalledProperties(properties)

            expect(properties).not.toHaveProperty(key)
            expect(properties).toEqual({ $feature_flag: 'kept' })
            expect(mockFlagInc).toHaveBeenCalledTimes(1)
            expect(mockFlagInc).toHaveBeenCalledWith(1)
        }
    )

    it('preserves whitelisted and $feature/ keys while stripping the rest', () => {
        const properties: Record<string, any> = {
            $feature_flag: 'flag-key',
            $feature_flag_response: true,
            '$feature/my-flag': 'variant-a',
            '$feature/another-flag': false,
            $lib: 'web',
            $current_url: 'https://example.com',
            $group_0: 'org-123',
            $groups: { organization: 'acme' },
            $set: { plan: 'pro' },
            environment: 'production',
            plan: 'pro',
            $active_feature_flags: ['flag-a', 'flag-b'],
        }

        stripFeatureFlagCalledProperties(properties)

        expect(properties).toEqual({
            $feature_flag: 'flag-key',
            $feature_flag_response: true,
            '$feature/my-flag': 'variant-a',
            '$feature/another-flag': false,
            $lib: 'web',
            $current_url: 'https://example.com',
            $group_0: 'org-123',
            $groups: { organization: 'acme' },
            $set: { plan: 'pro' },
            $active_feature_flags: ['flag-a', 'flag-b'],
        })
        expect(mockFlagInc).toHaveBeenCalledTimes(1)
        expect(mockFlagInc).toHaveBeenCalledWith(2)
    })

    it('leaves properties empty when every key is non-whitelisted', () => {
        const properties: Record<string, any> = { environment: 'prod', plan: 'pro', custom: 'x' }

        stripFeatureFlagCalledProperties(properties)

        expect(properties).toEqual({})
        expect(mockFlagInc).toHaveBeenCalledTimes(1)
        expect(mockFlagInc).toHaveBeenCalledWith(3)
    })

    it('is a no-op on empty properties', () => {
        const properties: Record<string, any> = {}

        stripFeatureFlagCalledProperties(properties)

        expect(properties).toEqual({})
        expect(mockFlagInc).not.toHaveBeenCalled()
    })

    it('only matches the $feature/ prefix at the start of the key, not as a substring', () => {
        const properties: Record<string, any> = {
            'has_$feature/in_middle': 'stripped',
            'feature/no-dollar': 'stripped',
        }

        stripFeatureFlagCalledProperties(properties)

        expect(properties).toEqual({})
        expect(mockFlagInc).toHaveBeenCalledTimes(1)
        expect(mockFlagInc).toHaveBeenCalledWith(2)
    })

    it.each([
        { desc: 'empty', properties: {}, expected: 0 },
        { desc: 'all kept', properties: { $feature_flag: 'f', $lib: 'web' }, expected: 2 },
        { desc: 'all stripped', properties: { environment: 'prod', plan: 'pro', custom: 'x' }, expected: 3 },
        { desc: 'mixed', properties: { $feature_flag: 'f', '$feature/x': 1, environment: 'prod' }, expected: 3 },
    ])('returns the pre-strip property count ($desc)', ({ properties, expected }) => {
        expect(stripFeatureFlagCalledProperties({ ...properties })).toBe(expected)
    })

    it.each([
        { desc: 'variant "control"', response: 'control' },
        { desc: 'variant "test"', response: 'test' },
        { desc: 'empty-string variant', response: '' },
    ])(
        'keeps all properties when $feature_flag_response is a variant string ($desc, experiment exposure)',
        ({ response }) => {
            const properties: Record<string, any> = {
                $feature_flag: 'flag-key',
                $feature_flag_response: response,
                environment: 'production',
                plan: 'pro',
                $active_feature_flags: ['flag-a', 'flag-b'],
                custom_breakdown_prop: 'mobile',
            }
            const unchanged = { ...properties }

            stripFeatureFlagCalledProperties(properties)

            expect(properties).toEqual(unchanged)
            expect(mockFlagInc).not.toHaveBeenCalled()
            expect(mockOutcomeLabels).toHaveBeenCalledWith('kept_multivariate')
        }
    )

    it.each([
        { desc: 'boolean true', response: true },
        { desc: 'boolean false', response: false },
        { desc: 'null', response: null },
        { desc: 'number', response: 30 },
        { desc: 'payload object', response: { enabled: false } },
    ])('strips non-whitelisted keys when $feature_flag_response is not a variant string ($desc)', ({ response }) => {
        const properties: Record<string, any> = {
            $feature_flag: 'flag-key',
            $feature_flag_response: response,
            environment: 'production',
        }

        stripFeatureFlagCalledProperties(properties)

        expect(properties).toEqual({ $feature_flag: 'flag-key', $feature_flag_response: response })
        expect(mockFlagInc).toHaveBeenCalledWith(1)
        expect(mockOutcomeLabels).toHaveBeenCalledWith('stripped')
    })

    it('strips non-whitelisted keys when $feature_flag_response is absent', () => {
        const properties: Record<string, any> = { $feature_flag: 'flag-key', environment: 'production' }

        stripFeatureFlagCalledProperties(properties)

        expect(properties).toEqual({ $feature_flag: 'flag-key' })
        expect(mockFlagInc).toHaveBeenCalledWith(1)
        expect(mockOutcomeLabels).toHaveBeenCalledWith('stripped')
    })
})
