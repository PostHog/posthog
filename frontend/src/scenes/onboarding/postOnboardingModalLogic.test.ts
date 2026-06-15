import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { FEATURE_FLAGS } from '~/lib/constants'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { onboardingLogic } from './onboardingLogic'
import { postOnboardingModalLogic } from './postOnboardingModalLogic'

describe('postOnboardingModalLogic', () => {
    let logic: ReturnType<typeof postOnboardingModalLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        logic = postOnboardingModalLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('flag constant is registered with kebab-case slug', () => {
        expect(FEATURE_FLAGS.POST_ONBOARDING_MODAL_EXPERIMENT).toBe('post-onboarding-modal-experiment')
    })

    it('mounts and connects featureFlagLogic values', () => {
        expect(logic.isMounted()).toBe(true)
        expect(logic.values.featureFlags).toBeTruthy()
        expect(logic.values.receivedFeatureFlags).not.toBeUndefined()
    })

    it('openPostOnboardingModal sets isModalOpen to true', async () => {
        await expectLogic(logic, () => {
            logic.actions.openPostOnboardingModal(ProductKey.PRODUCT_ANALYTICS)
        }).toMatchValues({
            isModalOpen: true,
        })
    })

    it('closePostOnboardingModal sets isModalOpen to false', async () => {
        await expectLogic(logic, () => {
            logic.actions.openPostOnboardingModal(ProductKey.PRODUCT_ANALYTICS)
        }).toMatchValues({ isModalOpen: true })

        await expectLogic(logic, () => {
            logic.actions.closePostOnboardingModal()
        }).toMatchValues({
            isModalOpen: false,
        })
    })

    it('openPostOnboardingModal sets modalShown to true and close does not reset it', async () => {
        expect(logic.values.modalShown).toBe(false)

        await expectLogic(logic, () => {
            logic.actions.openPostOnboardingModal(ProductKey.PRODUCT_ANALYTICS)
        }).toMatchValues({
            modalShown: true,
        })

        await expectLogic(logic, () => {
            logic.actions.closePostOnboardingModal()
        }).toMatchValues({
            modalShown: true,
        })
    })

    it('modalShown persists across logic remount', async () => {
        logic.actions.openPostOnboardingModal(ProductKey.PRODUCT_ANALYTICS)
        expect(logic.values.modalShown).toBe(true)

        logic.unmount()

        const logic2 = postOnboardingModalLogic()
        logic2.mount()

        expect(logic2.values.modalShown).toBe(true)

        logic2.unmount()
    })

    it('openPostOnboardingModal captures post_onboarding_modal_shown event', () => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        logic.actions.openPostOnboardingModal(ProductKey.PRODUCT_ANALYTICS)
        expect(captureSpy).toHaveBeenCalledWith(
            'post_onboarding_modal_shown',
            expect.objectContaining({
                product_key: ProductKey.PRODUCT_ANALYTICS,
                variant: expect.any(String),
            })
        )
        captureSpy.mockRestore()
    })

    it('ctaClicked captures post_onboarding_modal_cta_clicked event', () => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        logic.actions.ctaClicked()
        expect(captureSpy).toHaveBeenCalledWith(
            'post_onboarding_modal_cta_clicked',
            expect.objectContaining({
                variant: expect.any(String),
            })
        )
        captureSpy.mockRestore()
    })

    it('ctaClicked dispatches closePostOnboardingModal then openGlobalSetup', async () => {
        await expectLogic(logic, () => {
            logic.actions.ctaClicked()
        }).toDispatchActions(['ctaClicked', 'closePostOnboardingModal', 'openGlobalSetup'])
    })

    it('dismissModal captures post_onboarding_modal_dismissed event', () => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        logic.actions.dismissModal('close_button')
        expect(captureSpy).toHaveBeenCalledWith(
            'post_onboarding_modal_dismissed',
            expect.objectContaining({
                dismiss_method: 'close_button',
                variant: expect.any(String),
            })
        )
        captureSpy.mockRestore()
    })

    it('dismissModal dispatches closePostOnboardingModal', async () => {
        await expectLogic(logic, () => {
            logic.actions.dismissModal('close_button')
        }).toDispatchActions(['dismissModal', 'closePostOnboardingModal'])
    })

    it('dismissModal closes the modal', async () => {
        logic.actions.openPostOnboardingModal(ProductKey.PRODUCT_ANALYTICS)
        expect(logic.values.isModalOpen).toBe(true)
        await expectLogic(logic, () => {
            logic.actions.dismissModal('close_button')
        }).toMatchValues({
            isModalOpen: false,
        })
    })

    describe('onboardingLogic updateCurrentTeamSuccess branching', () => {
        let obLogic: ReturnType<typeof onboardingLogic.build>

        beforeEach(() => {
            obLogic = onboardingLogic()
            obLogic.mount()
            // Set productKey so the onboarding-completion guard passes
            obLogic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            userLogic.actions.loadUserSuccess({ is_organization_first_user: true } as any)
        })

        afterEach(() => {
            obLogic.unmount()
        })

        it('variant: dispatches openPostOnboardingModal when flag is test', async () => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.POST_ONBOARDING_MODAL_EXPERIMENT], {
                [FEATURE_FLAGS.POST_ONBOARDING_MODAL_EXPERIMENT]: 'test',
            })
            // The listener only branches on the experiment when isAwaitingPostOnboardingModal is true
            obLogic.actions.setAwaitingPostOnboardingModal(true)
            await expectLogic(logic, () => {
                obLogic.actions.updateCurrentTeamSuccess({} as any, {
                    has_completed_onboarding_for: { [ProductKey.PRODUCT_ANALYTICS]: true },
                })
            }).toDispatchActions(['openPostOnboardingModal'])
        })

        it('control: does NOT auto-open Quick Start (manual click only)', async () => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.POST_ONBOARDING_MODAL_EXPERIMENT], {
                [FEATURE_FLAGS.POST_ONBOARDING_MODAL_EXPERIMENT]: 'control',
            })
            await expectLogic(obLogic, () => {
                obLogic.actions.updateCurrentTeamSuccess({} as any, {
                    has_completed_onboarding_for: { [ProductKey.PRODUCT_ANALYTICS]: true },
                })
            }).toNotHaveDispatchedActions(['openGlobalSetup'])
        })

        it('control: does NOT auto-open Quick Start when flag is absent', async () => {
            // Do NOT set the feature flag — default state
            await expectLogic(obLogic, () => {
                obLogic.actions.updateCurrentTeamSuccess({} as any, {
                    has_completed_onboarding_for: { [ProductKey.PRODUCT_ANALYTICS]: true },
                })
            }).toNotHaveDispatchedActions(['openGlobalSetup'])
        })

        it('non-onboarding team save does NOT auto-open Quick Start', async () => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.POST_ONBOARDING_MODAL_EXPERIMENT], {
                [FEATURE_FLAGS.POST_ONBOARDING_MODAL_EXPERIMENT]: 'test',
            })
            // Payload does NOT include has_completed_onboarding_for for the current product
            await expectLogic(obLogic, () => {
                obLogic.actions.updateCurrentTeamSuccess({} as any, { name: 'My Team' } as any)
            }).toNotHaveDispatchedActions(['openGlobalSetup'])
        })

        it('skipOnboarding does NOT auto-open Quick Start', async () => {
            await expectLogic(obLogic, () => {
                obLogic.actions.skipOnboarding()
            }).toNotHaveDispatchedActions(['openGlobalSetup'])
        })
    })
})
