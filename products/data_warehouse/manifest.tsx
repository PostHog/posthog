import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Data Warehouse',
    scenes: {
        DataWarehouse: {
            name: 'Data Warehouse',
            import: () => import('./DataWarehouseScene'),
            projectBased: true,
            defaultDocsPath: '/docs/data-warehouse',
            activityScope: 'DataWarehouse',
        },
    },
    routes: {
        '/data-warehouse': ['DataWarehouse', 'dataWarehouse'],
    },
    urls: {
        dataWarehouse: (): string => '/data-warehouse',
    },
    treeItemsProducts: [
        {
            path: 'Data Warehouse',
            category: 'Analytics',
            iconType: 'database',
            href: urls.dataWarehouse(),
            flag: FEATURE_FLAGS.DATA_WAREHOUSE_SCENE,
        },
    ],
}
