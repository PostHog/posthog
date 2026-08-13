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
        DataCatalogMetric: {
            import: () => import('./frontend/DataCatalogMetricScene'),
            projectBased: true,
            name: 'Metric',
        },
    },
    routes: {
        '/data-catalog': ['DataCatalog', 'dataCatalog'],
        '/data-catalog/metrics/:name': ['DataCatalogMetric', 'dataCatalogMetric'],
    },
    redirects: {},
    urls: {
        dataCatalog: (tab?: string): string => `/data-catalog${tab ? `?tab=${tab}` : ''}`,
        dataCatalogMetric: (name: string): string => `/data-catalog/metrics/${name}`,
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
            tags: ['alpha'],
            sceneKey: 'DataCatalog',
        },
    ],
}
