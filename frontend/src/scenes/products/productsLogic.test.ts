import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { productsLogic } from './productsLogic'

describe('productsLogic', () => {
    let logic: ReturnType<typeof productsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/feature_flags/my_flags': {},
            },
        })
        initKeaTests()
        logic = productsLogic()
        logic.mount()
    })

    describe('product selection', () => {
        it('adds a product when toggled', async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleSelectedProduct(ProductKey.PRODUCT_ANALYTICS)
            }).toMatchValues({
                selectedProducts: [ProductKey.PRODUCT_ANALYTICS],
                firstProductOnboarding: ProductKey.PRODUCT_ANALYTICS,
            })
        })

        it('removes a product when toggled again', async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleSelectedProduct(ProductKey.PRODUCT_ANALYTICS)
                logic.actions.toggleSelectedProduct(ProductKey.SESSION_REPLAY)
            }).toMatchValues({
                selectedProducts: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
            })

            await expectLogic(logic, () => {
                logic.actions.toggleSelectedProduct(ProductKey.PRODUCT_ANALYTICS)
            }).toMatchValues({
                selectedProducts: [ProductKey.SESSION_REPLAY],
                firstProductOnboarding: ProductKey.SESSION_REPLAY,
            })
        })

        it('sets first product when adding to empty list', async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleSelectedProduct(ProductKey.FEATURE_FLAGS)
            }).toMatchValues({
                selectedProducts: [ProductKey.FEATURE_FLAGS],
                firstProductOnboarding: ProductKey.FEATURE_FLAGS,
            })
        })

        it('updates first product when it is removed', async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleSelectedProduct(ProductKey.PRODUCT_ANALYTICS)
                logic.actions.toggleSelectedProduct(ProductKey.SESSION_REPLAY)
                logic.actions.setFirstProductOnboarding(ProductKey.PRODUCT_ANALYTICS)
            }).toMatchValues({
                firstProductOnboarding: ProductKey.PRODUCT_ANALYTICS,
            })

            await expectLogic(logic, () => {
                logic.actions.toggleSelectedProduct(ProductKey.PRODUCT_ANALYTICS)
            }).toMatchValues({
                selectedProducts: [ProductKey.SESSION_REPLAY],
                firstProductOnboarding: ProductKey.SESSION_REPLAY,
            })
        })
    })

    describe('use case preselection', () => {
        it('sets preselected products from use case', async () => {
            await expectLogic(logic, () => {
                logic.actions.setPreselectedProducts([ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY])
            }).toMatchValues({
                preSelectedProducts: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
                selectedProducts: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
                firstProductOnboarding: ProductKey.PRODUCT_ANALYTICS,
            })
        })

        it('sets first product to first in preselected list', async () => {
            await expectLogic(logic, () => {
                logic.actions.setPreselectedProducts([ProductKey.FEATURE_FLAGS, ProductKey.EXPERIMENTS])
            }).toMatchValues({
                firstProductOnboarding: ProductKey.FEATURE_FLAGS,
            })
        })
    })

    describe('use case onboarding enabled', () => {
        it('returns true when use case is set and not pick_myself', async () => {
            await expectLogic(logic, () => {
                logic.actions.setUseCase('see_user_behavior')
            }).toMatchValues({
                useCase: 'see_user_behavior',
                isUseCaseOnboardingEnabled: true,
            })
        })

        it('returns false when use case is pick_myself', async () => {
            await expectLogic(logic, () => {
                logic.actions.setUseCase('pick_myself')
            }).toMatchValues({
                useCase: 'pick_myself',
                isUseCaseOnboardingEnabled: false,
            })
        })

        it('returns false when use case is null', async () => {
            await expectLogic(logic).toMatchValues({
                useCase: null,
                isUseCaseOnboardingEnabled: false,
            })
        })
    })

    describe('URL handling', () => {
        it('sets use case from URL parameter', async () => {
            router.actions.push('/products', { useCase: 'fix_issues' })

            await expectLogic(logic).toMatchValues({
                useCase: 'fix_issues',
            })
        })

        it('preselects products based on use case URL parameter', async () => {
            router.actions.push('/products', { useCase: 'see_user_behavior' })

            await expectLogic(logic).toMatchValues({
                useCase: 'see_user_behavior',
                preSelectedProducts: [
                    ProductKey.PRODUCT_ANALYTICS,
                    ProductKey.SESSION_REPLAY,
                    ProductKey.WEB_ANALYTICS,
                ],
                selectedProducts: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY, ProductKey.WEB_ANALYTICS],
            })
        })
    })

    describe('starting onboarding', () => {
        it('navigates to install step for most products', async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleSelectedProduct(ProductKey.PRODUCT_ANALYTICS)
                logic.actions.handleStartOnboarding()
            })

            expect(router.values.location.pathname).toBe(
                `/project/${MOCK_TEAM_ID}/onboarding/${ProductKey.PRODUCT_ANALYTICS}`
            )
        })

        it('navigates to authorized domains step for web analytics', async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleSelectedProduct(ProductKey.WEB_ANALYTICS)
                logic.actions.handleStartOnboarding()
            })

            expect(router.values.location.pathname).toBe(
                `/project/${MOCK_TEAM_ID}/onboarding/${ProductKey.WEB_ANALYTICS}`
            )
        })

        it('navigates to link data step for data warehouse', async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleSelectedProduct(ProductKey.DATA_WAREHOUSE)
                logic.actions.handleStartOnboarding()
            })

            expect(router.values.location.pathname).toBe(
                `/project/${MOCK_TEAM_ID}/onboarding/${ProductKey.DATA_WAREHOUSE}`
            )
        })

        it('does nothing if no first product is set', async () => {
            const initialPath = router.values.location.pathname

            await expectLogic(logic, () => {
                logic.actions.handleStartOnboarding()
            })

            expect(router.values.location.pathname).toBe(initialPath)
        })
    })
})
