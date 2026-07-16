import posthog from 'posthog-js'

import { FeatureFlagKey } from 'lib/constants'

import { initKeaTests } from '~/test/init'

import { featureFlagLogic } from './featureFlagLogic'

describe('featureFlagLogic', () => {
    let logic: ReturnType<typeof featureFlagLogic.build>

    const capturedFlagCalls = (flag: string): number =>
        (posthog.capture as jest.Mock).mock.calls.filter(
            ([event, props]) => event === '$feature_flag_called' && props?.$feature_flag === flag
        ).length

    beforeEach(() => {
        initKeaTests()
        ;(posthog.capture as jest.Mock).mockClear()
        logic = featureFlagLogic()
        logic.mount()
        // onFeatureFlags is mocked and never fires, so seed flags directly. Unique keys keep the
        // module-level `$feature_flag_called` dedupe from bleeding across assertions.
        logic.actions.setFeatureFlags([], { 'tracked-flag': true, 'silent-flag': true })
    })

    it('reading via featureFlags emits a $feature_flag_called event', () => {
        const value = (logic.values.featureFlags as Record<string, boolean | string | undefined>)['tracked-flag']

        expect(value).toBe(true)
        expect(capturedFlagCalls('tracked-flag')).toBe(1)
    })

    it('reading via featureFlagsWithoutTracking returns the value but emits no event', () => {
        const value = logic.values.featureFlagsWithoutTracking['silent-flag' as FeatureFlagKey]

        expect(value).toBe(true)
        expect(capturedFlagCalls('silent-flag')).toBe(0)
    })
})
