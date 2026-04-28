import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { getRelativeNextPath } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { onboardingLogic } from 'scenes/onboarding/onboardingLogic'
import { USE_CASE_OPTIONS, UseCaseOption, getRecommendedProducts } from 'scenes/onboarding/productRecommendations'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { availableOnboardingProducts } from '../utils'
import {
    getBrowsingHistoryFromPostHog,
    getBrowsingHistoryLabels,
    mapBrowsingHistoryToProducts,
} from './browsingHistoryMapping'
import type { productSelectionLogicType } from './productSelectionLogicType'

export type OnboardingStep = 'choose_path' | 'product_selection'
export type RecommendationSource = 'use_case' | 'browsing_history' | 'manual' | 'simplified' | 'multiproduct'

export const productSelectionLogic = kea<productSelectionLogicType>([
    path(['scenes', 'onboarding', 'productSelection', 'productSelectionLogic']),

    connect(() => ({
        actions: [
            teamLogic,
            ['addProductIntent'],
            onboardingLogic,
            ['setOnCompleteOnboardingRedirectUrl'],
            eventUsageLogic,
            ['reportOnboardingStarted', 'reportOnboardingProductSelectionPath', 'reportOnboardingProductToggled'],
        ],
        values: [teamLogic, ['currentTeam']],
    })),

    actions({
        // Step navigation
        setStep: (step: OnboardingStep) => ({ step }),

        // Browsing history
        setBrowsingHistory: (browsingHistory: string[]) => ({ browsingHistory }),

        // Use case selection
        selectUseCase: (useCase: UseCaseOption) => ({ useCase }),
        clearUseCase: true,

        // Product selection
        toggleProduct: (productKey: ProductKey) => ({ productKey }),
        setSelectedProducts: (productKeys: ProductKey[]) => ({ productKeys }),
        setFirstProductOnboarding: (productKey: ProductKey | null) => ({ productKey }),
        setRecommendationSource: (source: RecommendationSource) => ({ source }),

        // Pick myself path
        selectPickMyself: true,

        // Simplified single-select (picks one product and starts onboarding immediately)
        selectSingleProduct: (productKey: ProductKey) => ({ productKey }),

        // Continue to onboarding
        handleStartOnboarding: true,

        // Show all products toggle
        setShowAllProducts: (show: boolean) => ({ show }),
    }),

    reducers({
        currentStep: [
            'choose_path' as OnboardingStep,
            {
                setStep: (_, { step }) => step,
            },
        ],

        browsingHistory: [
            [] as string[],
            {
                setBrowsingHistory: (_, { browsingHistory }) => browsingHistory,
            },
        ],

        selectedUseCase: [
            null as UseCaseOption | null,
            {
                selectUseCase: (_, { useCase }) => useCase,
                clearUseCase: () => null,
            },
        ],

        selectedProducts: [
            [] as ProductKey[],
            {
                toggleProduct: (state, { productKey }) =>
                    state.includes(productKey) ? state.filter((k) => k !== productKey) : [...state, productKey],
                setSelectedProducts: (_, { productKeys }) => productKeys,
            },
        ],

        firstProductOnboarding: [
            null as ProductKey | null,
            {
                setFirstProductOnboarding: (_, { productKey }) => productKey,
                setSelectedProducts: (_, { productKeys }) => productKeys[0] || null,
            },
        ],

        recommendationSource: [
            'browsing_history' as RecommendationSource,
            {
                setRecommendationSource: (_, { source }) => source,
            },
        ],

        showAllProducts: [
            false,
            {
                setShowAllProducts: (_, { show }) => show,
            },
        ],
    }),

    selectors({
        browsingHistoryProducts: [
            (s) => [s.browsingHistory],
            (browsingHistory): ProductKey[] => mapBrowsingHistoryToProducts(browsingHistory),
        ],

        browsingHistoryLabels: [
            (s) => [s.browsingHistory],
            (browsingHistory): string[] => getBrowsingHistoryLabels(browsingHistory),
        ],

        hasBrowsingHistory: [(s) => [s.browsingHistory], (browsingHistory): boolean => browsingHistory.length > 0],

        useCaseProducts: [
            (s) => [s.selectedUseCase],
            (selectedUseCase): ProductKey[] => {
                if (!selectedUseCase) {
                    return []
                }
                return [...getRecommendedProducts(selectedUseCase)]
            },
        ],

        recommendedProducts: [
            (s) => [s.recommendationSource, s.browsingHistoryProducts, s.useCaseProducts],
            (source, browsingProducts, useCaseProducts): ProductKey[] => {
                switch (source) {
                    case 'use_case':
                        return [...new Set([...useCaseProducts, ...browsingProducts])]
                    case 'browsing_history':
                    case 'manual':
                    default:
                        return browsingProducts
                }
            },
        ],

        otherProducts: [
            (s) => [s.recommendedProducts],
            (recommendedProducts): ProductKey[] => {
                const allProducts = Object.keys(availableOnboardingProducts) as ProductKey[]
                return allProducts.filter((p) => !recommendedProducts.includes(p))
            },
        ],

        useCases: [() => [], () => USE_CASE_OPTIONS],

        canContinue: [(s) => [s.selectedProducts], (selectedProducts): boolean => selectedProducts.length > 0],

        recommendationSourceLabel: [
            (s) => [s.recommendationSource],
            (source): string => {
                switch (source) {
                    case 'use_case':
                        return 'based on your goal'
                    case 'browsing_history':
                        return 'based on your browsing'
                    case 'manual':
                    default:
                        return ''
                }
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        selectPickMyself: () => {
            const hasBrowsingHistory = values.hasBrowsingHistory
            actions.setRecommendationSource(hasBrowsingHistory ? 'browsing_history' : 'manual')

            if (hasBrowsingHistory) {
                actions.setSelectedProducts(values.browsingHistoryProducts)
            }

            actions.setShowAllProducts(true)
            actions.setStep('product_selection')

            // Analytics
            actions.reportOnboardingProductSelectionPath(hasBrowsingHistory ? 'browsing_history' : 'manual', {
                recommendedProducts: hasBrowsingHistory ? values.browsingHistoryProducts : [],
                hasBrowsingHistory,
            })
        },

        selectUseCase: ({ useCase }) => {
            actions.setRecommendationSource('use_case')

            // Get products from use case + browsing history
            const useCaseProducts = [...getRecommendedProducts(useCase)]
            const browsingProducts = values.browsingHistoryProducts
            const mergedProducts = [...new Set([...useCaseProducts, ...browsingProducts])]

            actions.setSelectedProducts(mergedProducts)
            actions.setStep('product_selection')

            // Analytics
            actions.reportOnboardingProductSelectionPath('use_case', {
                useCase,
                recommendedProducts: mergedProducts,
                hasBrowsingHistory: values.hasBrowsingHistory,
            })
        },

        toggleProduct: ({ productKey }) => {
            const isNowSelected = values.selectedProducts.includes(productKey)

            if (isNowSelected && values.firstProductOnboarding === null) {
                actions.setFirstProductOnboarding(productKey)
            } else if (!isNowSelected && values.firstProductOnboarding === productKey) {
                const remaining = values.selectedProducts.filter((k) => k !== productKey)
                actions.setFirstProductOnboarding(remaining[0] || null)
            }

            actions.reportOnboardingProductToggled(productKey, isNowSelected, values.recommendationSource)
        },

        selectSingleProduct: ({ productKey }) => {
            actions.setSelectedProducts([productKey])
            actions.setFirstProductOnboarding(productKey)
            actions.setRecommendationSource('simplified')
            actions.handleStartOnboarding()
        },

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

            router.actions.push(urls.onboarding({ productKey: values.firstProductOnboarding, stepKey }))

            values.selectedProducts.forEach((productKey) => {
                actions.addProductIntent({
                    product_type: productKey,
                    intent_context:
                        values.firstProductOnboarding === productKey
                            ? ProductIntentContext.ONBOARDING_PRODUCT_SELECTED_PRIMARY
                            : ProductIntentContext.ONBOARDING_PRODUCT_SELECTED_SECONDARY,
                })
            })

            // Analytics
            window.posthog?.capture('onboarding_products_confirmed', {
                recommendation_source: values.recommendationSource,
                selected_products: values.selectedProducts,
                first_product: values.firstProductOnboarding,
                browsing_history: values.browsingHistory,
            })
        },
    })),

    afterMount(({ actions }) => {
        const browsingHistory = getBrowsingHistoryFromPostHog()
        if (browsingHistory.length > 0) {
            actions.setBrowsingHistory(browsingHistory)

            // Pre-select products based on browsing history
            const browsingProducts = mapBrowsingHistoryToProducts(browsingHistory)
            if (browsingProducts.length > 0) {
                actions.setSelectedProducts(browsingProducts)
            }
        }

        actions.reportOnboardingStarted('product_selection')
    }),
])
