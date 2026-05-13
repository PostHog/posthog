import { FEATURE_FLAGS } from 'lib/constants'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Catalog',
    scenes: {
        CatalogList: {
            import: () => import('./frontend/CatalogListScene'),
            projectBased: true,
            name: 'Catalog',
            activityScope: 'CatalogNode',
            layout: 'app-container',
            iconType: 'data_warehouse',
        },
        CatalogDefinition: {
            import: () => import('./frontend/CatalogDefinitionScene'),
            projectBased: true,
            name: 'Catalog definition',
            activityScope: 'CatalogNode',
            layout: 'app-container',
            iconType: 'data_warehouse',
        },
    },
    routes: {
        '/catalog': ['CatalogList', 'catalog'],
        '/catalog/definitions/:id': ['CatalogDefinition', 'catalogDefinition'],
    },
    urls: {
        catalog: (): string => '/catalog',
        catalogDefinition: (id: string): string => `/catalog/definitions/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Catalog',
            intents: [ProductKey.CATALOG],
            category: ProductItemCategory.UNRELEASED,
            href: '/catalog',
            iconType: 'data_warehouse' as FileSystemIconType,
            iconColor: ['var(--color-product-data-warehouse-light)'] as FileSystemIconColor,
            flag: FEATURE_FLAGS.CATALOG,
            tags: ['alpha'],
            sceneKey: 'CatalogList',
        },
    ],
}
