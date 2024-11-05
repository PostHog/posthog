import { actions, kea, listeners, path, reducers } from 'kea'

import { ProductKey } from '~/types'

import type { productsLogicType } from './productsLogicType'

export const productsLogic = kea<productsLogicType>([
    path(['scenes', 'products', 'productsLogic']),
    actions(() => ({
        toggleSelectedProduct: (productKey: ProductKey) => ({ productKey }),
        setFirstProductOnboarding: (productKey: ProductKey) => ({ productKey }),
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
        toggleSelectedProduct: ({ productKey }) => {
            if (values.selectedProducts.includes(productKey) && values.firstProductOnboarding === null) {
                actions.setFirstProductOnboarding(productKey)
            } else if (!values.selectedProducts.includes(productKey) && values.firstProductOnboarding === productKey) {
                actions.setFirstProductOnboarding(values.selectedProducts[0] || null)
            }
        },
    })),
])
