import { kea } from 'kea'
import { BillingProductV2Type, ProductKey } from '~/types'
import { urls } from 'scenes/urls'

import type { onboardingLogicType } from './onboardingLogicType'
import { billingLogic } from 'scenes/billing/billingLogic'

export interface OnboardingLogicProps {
    productKey: ProductKey | null
}

export const onboardingLogic = kea<onboardingLogicType>({
    props: {} as OnboardingLogicProps,
    path: ['scenes', 'onboarding', 'onboardingLogic'],
    connect: {
        values: [billingLogic, ['billing']],
        actions: [billingLogic, ['loadBillingSuccess']],
    },
    actions: {
        setProduct: (product: BillingProductV2Type | null) => ({ product }),
        setProductKey: (productKey: string | null) => ({ productKey }),
        setOnboardingStep: (onboardingStep: number) => ({ onboardingStep }),
        incrementOnboardingStep: true,
        setTotalOnboardingSteps: (totalOnboardingSteps: number) => ({ totalOnboardingSteps }),
        completeOnboarding: true,
    },
    reducers: () => ({
        productKey: [
            null as string | null,
            {
                setProductKey: (_, { productKey }) => productKey,
            },
        ],
        product: [
            null as BillingProductV2Type | null,
            {
                setProduct: (_, { product }) => product,
            },
        ],
        onboardingStep: [
            1,
            {
                setOnboardingStep: (_, { onboardingStep }) => onboardingStep,
                incrementOnboardingStep: (state) => state + 1,
            },
        ],
        totalOnboardingSteps: [
            1,
            {
                setTotalOnboardingSteps: (_, { totalOnboardingSteps }) => totalOnboardingSteps,
            },
        ],
        onCompleteOnbardingRedirectUrl: [
            urls.default() as string,
            {
                setProductKey: (_, { productKey }) => {
                    switch (productKey) {
                        case 'product_analytics':
                            return urls.default()
                        case 'session_replay':
                            return urls.replay()
                        case 'feature_flags':
                            return urls.featureFlags()
                        default:
                            return urls.default()
                    }
                },
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        loadBillingSuccess: () => {
            actions.setProduct(values.billing?.products.find((p) => p.type === values.productKey) || null)
        },
        setProduct: ({ product }) => {
            if (!product) {
                window.location.href = urls.default()
                return
            }
        },
        setProductKey: ({ productKey }) => {
            if (!productKey) {
                window.location.href = urls.default()
                return
            }
            if (values.billing?.products?.length) {
                actions.setProduct(values.billing?.products.find((p) => p.type === values.productKey) || null)
            }
        },
        completeOnboarding: () => {
            window.location.href = values.onCompleteOnbardingRedirectUrl
        },
    }),
    urlToAction: ({ actions }) => ({
        '/onboarding/:productKey': ({ productKey }) => {
            if (!productKey) {
                window.location.href = urls.default()
                return
            }
            actions.setProductKey(productKey)
            actions.setOnboardingStep(1)
        },
    }),
})
