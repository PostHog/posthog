import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'
import { FileSystemIconColor, ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Data warehouse',
    scenes: {
        DataWarehouse: {
            name: 'Data warehouse',
            import: () => import('./DataWarehouseScene'),
            projectBased: true,
            defaultDocsPath: '/docs/data-warehouse',
            activityScope: 'DataWarehouse',
            description:
                'Manage your data warehouse sources and queries. New source syncs are always free for the first 7 days',
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
            path: 'Data warehouse',
            category: 'Unreleased',
            href: urls.dataWarehouse(),
            flag: FEATURE_FLAGS.DATA_WAREHOUSE_SCENE,
            iconType: 'data_warehouse' as FileSystemIconType,
            iconColor: ['var(--color-product-data-warehouse-light)'] as FileSystemIconColor,
            sceneKey: 'DataWarehouse',
        },
    ],
}
