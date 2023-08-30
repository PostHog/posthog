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
    }),
    urlToAction: ({ actions }) => ({
        '/onboarding/:productKey': ({ productKey }) => {
            if (!productKey) {
                window.location.href = urls.default()
                return
            }
            actions.setProductKey(productKey)
        },
    }),
})
