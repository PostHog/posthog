import { applyPageFlagOverrides } from './pageFlagOverrides'

describe('applyPageFlagOverrides', () => {
    afterEach(() => {
        delete (window as any).posthog
    })

    it('reports a page without posthog-js on window', () => {
        expect(applyPageFlagOverrides({ beta: true })).toEqual({ available: false, overrides: {} })
    })

    it.each([
        [
            'applies overrides',
            { beta: true, plan: 'test' },
            [[{ flags: { beta: true, plan: 'test' } }]],
            { beta: true, plan: 'test' },
        ],
        ['clears overrides for an empty map', {}, [[false]], {}],
        ['only reads for null', null, [], { old: true }],
    ])('%s', (_, flags, expectedCalls, expectedOverrides) => {
        let stored: Record<string, string | boolean> = { old: true }
        const overrideFeatureFlags = jest.fn((overrides: { flags: Record<string, string | boolean> } | false) => {
            stored = overrides ? overrides.flags : {}
        })
        ;(window as any).posthog = {
            featureFlags: { overrideFeatureFlags },
            get_property: (key: string) => (key === '$override_feature_flags' ? stored : undefined),
        }

        const result = applyPageFlagOverrides(flags)

        expect(overrideFeatureFlags.mock.calls).toEqual(expectedCalls)
        expect(result).toEqual({ available: true, overrides: expectedOverrides })
    })
})
