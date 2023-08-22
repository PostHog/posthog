import { kea } from 'kea'
import { Product, ProductKey } from '~/types'
import { products } from 'scenes/products/productsLogic'
import { urls } from 'scenes/urls'

import type { onboardingLogicType } from './onboardingLogicType'

export interface OnboardingLogicProps {
    productKey: ProductKey | null
}

export const onboardingLogic = kea<onboardingLogicType>({
    props: {} as OnboardingLogicProps,
    path: ['scenes', 'onboarding', 'onboardingLogic'],
    actions: {
        setProduct: (productKey: string | null) => ({ productKey }),
    },
    reducers: {
        product: [
            null as Product | null,
            {
                setProduct: (_, { productKey }) => products.find((p) => p.key === productKey) || null,
            },
        ],
    },
    selectors: {},
    urlToAction: ({ actions }) => ({
        '/onboarding/:productKey': ({ productKey }) => {
            if (!productKey || !products.find((p) => p.key === productKey)) {
                window.location.href = urls.default()
                return
            }
            actions.setProduct(productKey)
        },
    }),
})
