import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { router } from 'kea-router'
import { getRelativeNextPath } from 'lib/utils'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { onboardingLogic } from 'scenes/onboarding/onboardingLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductKey, OnboardingStepKey } from '~/types'

import type { productsLogicType } from './productsLogicType'

export const productsLogic = kea<productsLogicType>([
    path(['scenes', 'products', 'productsLogic']),
    connect(() => ({
        actions: [teamLogic, ['addProductIntent'], onboardingLogic, ['setOnCompleteOnboardingRedirectUrl']],
    })),
    actions(() => ({
        toggleSelectedProduct: (productKey: ProductKey) => ({ productKey }),
        setFirstProductOnboarding: (productKey: ProductKey) => ({ productKey }),
        handleStartOnboarding: () => true,
    })),
    reducers({
        selectedProducts: [
            [] as ProductKey[],
            {
                toggleSelectedProduct: (state, { productKey }) =>
                    state.includes(productKey) ? state.filter((key) => key !== productKey) : [...state, productKey],
            },
        ],
        firstProductOnboarding: [
            null as ProductKey | null,
            {
                setFirstProductOnboarding: (_, { productKey }) => productKey,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        handleStartOnboarding: () => {
            const nextUrl = getRelativeNextPath(router.values.searchParams['next'], location)

            if (nextUrl && nextUrl !== '/') {
                actions.setOnCompleteOnboardingRedirectUrl(nextUrl)
            }

            if (!values.firstProductOnboarding) {
                return
            }

            const isFromWizard = router.values.searchParams['source'] === 'wizard'

            const requiresFurtherSetup = [ProductKey.ERROR_TRACKING, ProductKey.FEATURE_FLAGS, ProductKey.EXPERIMENTS]

            const secondStepKey =
                values.firstProductOnboarding === ProductKey.WEB_ANALYTICS
                    ? OnboardingStepKey.AUTHORIZED_DOMAINS
                    : OnboardingStepKey.PRODUCT_CONFIGURATION

            const stepKey =
                values.firstProductOnboarding === ProductKey.DATA_WAREHOUSE
                    ? OnboardingStepKey.LINK_DATA
                    : isFromWizard && !requiresFurtherSetup.includes(values.firstProductOnboarding)
                    ? secondStepKey
                    : OnboardingStepKey.INSTALL

            router.actions.push(urls.onboarding(values.firstProductOnboarding, stepKey))
            values.selectedProducts.forEach((productKey) => {
                actions.addProductIntent({
                    product_type: productKey as ProductKey,
                    intent_context:
                        values.firstProductOnboarding === productKey
                            ? ProductIntentContext.ONBOARDING_PRODUCT_SELECTED_PRIMARY
                            : ProductIntentContext.ONBOARDING_PRODUCT_SELECTED_SECONDARY,
                })
            })
        },
        toggleSelectedProduct: ({ productKey }) => {
            if (values.selectedProducts.includes(productKey) && values.firstProductOnboarding === null) {
                actions.setFirstProductOnboarding(productKey)
            } else if (!values.selectedProducts.includes(productKey) && values.firstProductOnboarding === productKey) {
                actions.setFirstProductOnboarding(values.selectedProducts[0] || null)
            }
        },
    })),
])
