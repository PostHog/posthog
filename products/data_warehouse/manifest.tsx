import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'
import { FileSystemIconColor, ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Data Warehouse',
    scenes: {
        DataWarehouse: {
            name: 'Data Warehouse',
            import: () => import('./DataWarehouseScene'),
            projectBased: true,
            defaultDocsPath: '/docs/data-warehouse',
            activityScope: 'DataWarehouse',
            description: 'Manage your data warehouse sources and queries',
            iconType: 'data_warehouse',
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
            category: 'Unreleased',
            href: urls.dataWarehouse(),
            flag: FEATURE_FLAGS.DATA_WAREHOUSE_SCENE,
            iconType: 'data_warehouse' as FileSystemIconType,
            iconColor: ['var(--color-product-data-warehouse-light)'] as FileSystemIconColor,
            sceneKey: 'DataWarehouse',
        },
    ],
}
