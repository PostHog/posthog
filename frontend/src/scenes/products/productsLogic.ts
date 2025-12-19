import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'

import { getRelativeNextPath } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { onboardingLogic } from 'scenes/onboarding/onboardingLogic'
import { getRecommendedProducts } from 'scenes/onboarding/productRecommendations'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import type { productsLogicType } from './productsLogicType'

export const productsLogic = kea<productsLogicType>([
    path(['scenes', 'products', 'productsLogic']),
    connect(() => ({
        actions: [
            teamLogic,
            ['addProductIntent'],
            onboardingLogic,
            ['setOnCompleteOnboardingRedirectUrl'],
            eventUsageLogic,
            ['reportOnboardingStarted'],
        ],
    })),
    actions(() => ({
        toggleSelectedProduct: (productKey: ProductKey) => ({ productKey }),
        setFirstProductOnboarding: (productKey: ProductKey) => ({ productKey }),
        handleStartOnboarding: () => true,
        setPreselectedProducts: (productKeys: ProductKey[]) => ({ productKeys }),
        setUseCase: (useCase: string | null) => ({ useCase }),
    })),
    reducers({
        selectedProducts: [
            [] as ProductKey[],
            {
                toggleSelectedProduct: (state, { productKey }) =>
                    state.includes(productKey) ? state.filter((key) => key !== productKey) : [...state, productKey],
                setPreselectedProducts: (_, { productKeys }) => productKeys,
            },
        ],
        firstProductOnboarding: [
            null as ProductKey | null,
            {
                setFirstProductOnboarding: (_, { productKey }) => productKey,
                setPreselectedProducts: (_, { productKeys }) => productKeys[0] || null,
            },
        ],
        preSelectedProducts: [
            [] as ProductKey[],
            {
                setPreselectedProducts: (_, { productKeys }) => productKeys,
            },
        ],
        useCase: [
            null as string | null,
            {
                setUseCase: (_, { useCase }) => useCase,
            },
        ],
    }),
    selectors({
        isUseCaseOnboardingEnabled: [
            (s) => [s.useCase],
            (useCase: string | null): boolean => !!useCase && useCase !== 'pick_myself',
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
    urlToAction(({ actions }) => ({
        [urls.products()]: (_: any, searchParams: Record<string, any>) => {
            if (searchParams.useCase) {
                actions.setUseCase(searchParams.useCase)
                const recommendedProducts = getRecommendedProducts(searchParams.useCase)
                if (recommendedProducts.length > 0) {
                    actions.setPreselectedProducts([...recommendedProducts])

                    // Track analytics when products are preselected based on use case
                    if (window.posthog) {
                        window.posthog.capture('onboarding_products_preselected', {
                            use_case: searchParams.useCase,
                            recommended_products: recommendedProducts,
                        })
                    }
                }
            } else {
                // User went directly to products page (not via use case selection)
                actions.reportOnboardingStarted('product_selection')
            }
        },
    })),
])
