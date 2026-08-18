import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { productSelectionLogic } from './productSelectionLogic'

jest.mock('posthog-js')

function onboardingStartedCaptures(): unknown[][] {
    return (posthog.capture as jest.Mock).mock.calls.filter(([event]) => event === 'onboarding started')
}

function setOnboardingVariant(variant: boolean | string): void {
    featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT], {
        [FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT]: variant,
    })
}

describe('productSelectionLogic', () => {
    let logic: ReturnType<typeof productSelectionLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        featureFlagLogic.mount()
        logic = productSelectionLogic()
    })

    afterEach(() => {
        logic.unmount()
        featureFlagLogic.unmount()
    })

    it('reports onboarding started once when control is already assigned', async () => {
        setOnboardingVariant('control')

        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()

        expect(onboardingStartedCaptures()).toEqual([
            [
                'onboarding started',
                expect.objectContaining({
                    entry_point: 'product_selection',
                }),
            ],
        ])
    })

    it('waits for a control assignment before reporting onboarding started', async () => {
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        expect(onboardingStartedCaptures()).toHaveLength(0)

        await expectLogic(logic, () => setOnboardingVariant('control')).toFinishAllListeners()
        expect(onboardingStartedCaptures()).toHaveLength(1)
    })

    it('does not trust a persisted control assignment before flags resolve', async () => {
        featureFlagLogic.unmount()
        localStorage.setItem(
            'lib.logic.featureFlagLogic.featureFlags',
            JSON.stringify({ [FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT]: 'control' })
        )
        initKeaTests()
        featureFlagLogic.mount()
        logic = productSelectionLogic()

        expect(featureFlagLogic.values.featureFlags[FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT]).toBe('control')
        expect(featureFlagLogic.values.receivedFeatureFlags).toBe(false)

        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        await expectLogic(logic, () => setOnboardingVariant('self-driving')).toFinishAllListeners()

        expect(onboardingStartedCaptures()).toHaveLength(0)
    })

    it('does not report legacy onboarding started for self-driving', async () => {
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()

        await expectLogic(logic, () => setOnboardingVariant('self-driving')).toFinishAllListeners()

        expect(onboardingStartedCaptures()).toHaveLength(0)
    })

    it('reports onboarding started once when control is received repeatedly', async () => {
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()

        await expectLogic(logic, () => {
            setOnboardingVariant('control')
            setOnboardingVariant('control')
        }).toFinishAllListeners()

        expect(onboardingStartedCaptures()).toHaveLength(1)
    })

    it.each([undefined, true, 'legacy'])('does not report onboarding started for %p', async (variant) => {
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()

        if (variant !== undefined) {
            await expectLogic(logic, () => setOnboardingVariant(variant)).toFinishAllListeners()
        }

        expect(onboardingStartedCaptures()).toHaveLength(0)
    })
})
