import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getAppContext } from 'lib/utils/getAppContext'

import type { UserProductListItem } from '~/queries/schema/schema-general'

import type { customProductsLogicType } from './customProductsLogicType'

export const customProductsLogic = kea<customProductsLogicType>([
    path(['layout', 'panel-layout', 'ProjectTree', 'customProductsLogic']),
    loaders(() => ({
        customProducts: [
            getAppContext()?.custom_products ?? [],
            {
                loadCustomProducts: async (): Promise<UserProductListItem[]> => {
                    const response = await api.userProductList.list()

                    return response.results ?? []
                },
            },
        ],
    })),
])
