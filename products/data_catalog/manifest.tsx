import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'DataCatalog',
    scenes: {
        DataCatalog: {
            import: () => import('./frontend/DataCatalogScene'),
            projectBased: true,
            name: 'Data catalog',
            layout: 'app-container',
            iconType: 'data_warehouse',
            description: 'Review and manage governed metrics, certifications, and relationships for your data.',
        },
    },
    routes: {
        '/data-catalog': ['DataCatalog', 'dataCatalog'],
    },
    redirects: {},
    urls: {
        dataCatalog: (tab?: string): string => `/data-catalog${tab ? `?tab=${tab}` : ''}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Data catalog',
            intents: [ProductKey.DATA_CATALOG],
            category: ProductItemCategory.ANALYTICS,
            iconType: 'data_warehouse',
            href: urls.dataCatalog(),
            flag: FEATURE_FLAGS.PRODUCT_DATA_CATALOG,
            sceneKey: 'DataCatalog',
        },
    ],
}
