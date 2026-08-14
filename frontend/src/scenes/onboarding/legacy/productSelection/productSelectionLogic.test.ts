import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { productSelectionLogic } from './productSelectionLogic'

/**
 * The onboarding experiment reads its variant off the `onboarding started` event. `appLogic`
 * releases the app after 3 seconds whether or not the flags arrived, and an unresolved flag renders
 * this legacy flow, so an ungated emission produces exposures with no
 * `$feature/onboarding-flow-variant` property. The experiment discards those, and only control can
 * ever produce one.
 */
describe('productSelectionLogic onboarding exposure', () => {
    let logic: ReturnType<typeof productSelectionLogic.build>
    let flagsLogic: ReturnType<typeof featureFlagLogic.build>
    let capture: jest.SpyInstance

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        flagsLogic = featureFlagLogic()
        flagsLogic.mount()
        capture = jest.spyOn(posthog, 'capture').mockImplementation()
    })

    afterEach(() => {
        logic?.unmount()
        flagsLogic.unmount()
        capture.mockRestore()
    })

    const onboardingStartedCount = (): number =>
        capture.mock.calls.filter(([event]) => event === 'onboarding started').length

    const receiveFlags = (variant: string): void => {
        flagsLogic.actions.setFeatureFlags([FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT], {
            [FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT]: variant,
        })
    }

    const mountLogic = (): void => {
        logic = productSelectionLogic()
        logic.mount()
    }

    it('holds the event until the flags arrive, then emits it once', () => {
        mountLogic()
        expect(onboardingStartedCount()).toBe(0)

        receiveFlags('control')
        expect(onboardingStartedCount()).toBe(1)

        receiveFlags('control')
        expect(onboardingStartedCount()).toBe(1)
    })

    it('emits the event on mount when the flags are already loaded', () => {
        receiveFlags('control')
        mountLogic()
        expect(onboardingStartedCount()).toBe(1)

        receiveFlags('control')
        expect(onboardingStartedCount()).toBe(1)
    })

    it('emits nothing when the late flags select the self-driving flow', () => {
        mountLogic()
        receiveFlags('self-driving')
        expect(onboardingStartedCount()).toBe(0)
    })
})
