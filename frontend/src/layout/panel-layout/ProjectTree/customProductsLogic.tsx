import { kea, path, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'

import type { customProductsLogicType } from './customProductsLogicType'

export interface UserProductListItem {
    id: string
    product_path: string
    enabled: boolean
    created_at: string
    updated_at: string
}

export const customProductsLogic = kea<customProductsLogicType>([
    path(['layout', 'panel-layout', 'ProjectTree', 'customProductsLogic']),
    lazyLoaders({
        customProducts: [
            [] as UserProductListItem[],
            {
                loadCustomProducts: async (): Promise<UserProductListItem[]> => {
                    const response = await api.userProductList.list()
                    return response.results
                },
            },
        ],
    }),
    selectors({
        customProductPaths: [
            (s) => [s.customProducts],
            (customProducts: UserProductListItem[]): Set<string> => {
                return new Set(customProducts.map((item) => item.product_path))
            },
        ],
    }),
])
