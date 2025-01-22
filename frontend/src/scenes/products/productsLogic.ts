import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { router } from 'kea-router'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/types'

import { onboardingLogic } from '../onboarding/onboardingLogic'
import type { productsLogicType } from './productsLogicType'

export const productsLogic = kea<productsLogicType>([
    path(['scenes', 'products', 'productsLogic']),
    connect({
        actions: [onboardingLogic, ['setIncludeIntro'], teamLogic, ['addProductIntent']],
    }),
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
            if (!values.firstProductOnboarding) {
                return
            }

            actions.setIncludeIntro(false)
            router.actions.push(urls.onboarding(values.firstProductOnboarding))
            values.selectedProducts.forEach((productKey) => {
                actions.addProductIntent({
                    product_type: productKey as ProductKey,
                    intent_context:
                        values.firstProductOnboarding === productKey
                            ? 'onboarding product selected - primary'
                            : 'onboarding product selected - secondary',
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
