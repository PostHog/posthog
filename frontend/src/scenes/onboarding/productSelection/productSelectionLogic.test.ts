import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { onboardingLogic } from 'scenes/onboarding/onboardingLogic'
import { productSelectionLogic } from 'scenes/onboarding/productSelection/productSelectionLogic'

import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

describe('productSelectionLogic', () => {
    let logic: ReturnType<typeof productSelectionLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/billing/': () => [200, {}],
            },
            patch: {
                '/api/projects/:team/add_product_intent/': () => [200, {}],
            },
        })
        initKeaTests()
        onboardingLogic.mount()
        logic = productSelectionLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('handleStartOnboarding', () => {
        it('falls back to selectedProducts[0] when firstProductOnboarding is null', async () => {
            const pushSpy = jest.spyOn(router.actions, 'push')

            // Simulate the state the multi-select carousel can briefly leave us in:
            // products are picked but firstProductOnboarding never got explicitly set.
            await expectLogic(logic, () => {
                logic.actions.setSelectedProducts([ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY])
                logic.actions.setFirstProductOnboarding(null)
            }).toMatchValues({
                selectedProducts: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
                firstProductOnboarding: null,
            })

            await expectLogic(logic, () => {
                logic.actions.handleStartOnboarding()
            }).toFinishAllListeners()

            expect(pushSpy).toHaveBeenCalled()
            const lastCall = pushSpy.mock.calls[pushSpy.mock.calls.length - 1]?.[0]
            expect(lastCall).toContain(ProductKey.PRODUCT_ANALYTICS)

            expect(logic.values.firstProductOnboarding).toBe(ProductKey.PRODUCT_ANALYTICS)

            pushSpy.mockRestore()
        })

        it('does nothing when neither firstProductOnboarding nor selectedProducts are set', async () => {
            const pushSpy = jest.spyOn(router.actions, 'push')
            const previousCalls = pushSpy.mock.calls.length

            await expectLogic(logic, () => {
                logic.actions.handleStartOnboarding()
            }).toFinishAllListeners()

            expect(pushSpy.mock.calls.length).toBe(previousCalls)

            pushSpy.mockRestore()
        })

        it('uses the explicitly set firstProductOnboarding when present', async () => {
            const pushSpy = jest.spyOn(router.actions, 'push')

            await expectLogic(logic, () => {
                logic.actions.setSelectedProducts([ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY])
                logic.actions.setFirstProductOnboarding(ProductKey.SESSION_REPLAY)
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.handleStartOnboarding()
            }).toFinishAllListeners()

            const lastCall = pushSpy.mock.calls[pushSpy.mock.calls.length - 1]?.[0]
            expect(lastCall).toContain(ProductKey.SESSION_REPLAY)

            pushSpy.mockRestore()
        })
    })
})
