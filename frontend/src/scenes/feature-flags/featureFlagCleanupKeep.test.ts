import { cleanupKeepToRequest, getCleanupKeepOptions } from './featureFlagCleanupKeep'

describe('featureFlagCleanupKeep', () => {
    it('offers on and off paths for a boolean flag and variants plus off for a multivariate flag', () => {
        expect(getCleanupKeepOptions({ filters: { groups: [] } }).map((option) => option.value)).toEqual([
            'enabled',
            'disabled',
        ])
        expect(
            getCleanupKeepOptions({
                filters: {
                    groups: [],
                    multivariate: {
                        variants: [
                            { key: 'control', rollout_percentage: 50 },
                            { key: 'a:b', rollout_percentage: 50 },
                        ],
                    },
                },
            }).map((option) => option.value)
        ).toEqual(['variant:control', 'variant:a:b', 'disabled'])
    })

    it.each([
        ['enabled', { keep: 'enabled', repository: null }],
        ['disabled', { keep: 'disabled', repository: 'posthog/posthog' }],
        ['variant:a:b', { keep: 'variant', variant_key: 'a:b', repository: 'posthog/posthog' }],
    ])('maps %s to the request body', (keep, expected) => {
        const repository = keep === 'enabled' ? null : 'posthog/posthog'
        expect(cleanupKeepToRequest(keep, repository)).toEqual(expected)
    })
})
