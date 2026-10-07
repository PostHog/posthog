import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { areClientFeatureFlagsHonored, featureFlagLogic } from './featureFlagLogic'

describe('featureFlagLogic', () => {
    describe('areClientFeatureFlagsHonored', () => {
        it.each([
            [null, false],
            [{ cloud: false, is_debug: false }, false],
            [{ cloud: true, is_debug: false }, true],
            [{ cloud: false, is_debug: true }, true],
            [{ cloud: true, is_debug: true }, true],
        ])('preflight %s returns %s', (preflight, expected) => {
            expect(areClientFeatureFlagsHonored(preflight)).toBe(expected)
        })
    })

    describe('receivedFeatureFlags', () => {
        afterEach(() => {
            delete (posthog as any).config
        })

        // The mocked onFeatureFlags never calls back, as posthog-js does not when flags are off.
        it.each([
            ['flags disabled', { advanced_disable_flags: true }, true],
            ['flags enabled', { advanced_disable_flags: false }, false],
        ])('with %s is %s before any flags arrive', (_name, config, expected) => {
            ;(posthog as any).config = config
            initKeaTests()

            const logic = featureFlagLogic()
            logic.mount()

            expect(logic.values.receivedFeatureFlags).toBe(expected)
        })
    })

    describe('receivedServerFeatureFlags', () => {
        afterEach(() => {
            delete (posthog as any).config
        })

        it.each([
            ['the bootstrapped flags', undefined, false],
            ['a /flags response', { errorsLoading: false }, true],
            ['a failed /flags response', { errorsLoading: true }, true],
        ])('after %s is %s', (_name, context, expected) => {
            initKeaTests()
            const logic = featureFlagLogic()
            logic.mount()
            const callback = jest.mocked(posthog.onFeatureFlags).mock.calls.at(-1)![0]

            callback(['my-flag'], { 'my-flag': true }, context)

            expect(logic.values.receivedFeatureFlags).toBe(true)
            expect(logic.values.receivedServerFeatureFlags).toBe(expected)
        })
    })
})
