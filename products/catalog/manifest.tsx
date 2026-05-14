import { FEATURE_FLAGS } from 'lib/constants'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Catalog',
    scenes: {
        CatalogProposals: {
            import: () => import('./frontend/CatalogProposalsScene'),
            projectBased: true,
            name: 'Proposals',
            activityScope: 'CatalogNode',
            layout: 'app-container',
            iconType: 'data_warehouse',
        },
        CatalogList: {
            import: () => import('./frontend/CatalogListScene'),
            projectBased: true,
            name: 'Catalog',
            activityScope: 'CatalogNode',
            layout: 'app-container',
            iconType: 'data_warehouse',
        },
        CatalogGraph: {
            import: () => import('./frontend/CatalogGraphScene'),
            projectBased: true,
            name: 'Catalog graph',
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
        '/catalog': ['CatalogProposals', 'catalog'],
        '/catalog/proposals/:id': ['CatalogProposals', 'catalogProposal'],
        '/catalog/list': ['CatalogList', 'catalogList'],
        '/catalog/graph': ['CatalogGraph', 'catalogGraph'],
        '/catalog/definitions/:id': ['CatalogDefinition', 'catalogDefinition'],
    },
    urls: {
        catalog: (): string => '/catalog',
        catalogProposal: (id: string): string => `/catalog/proposals/${id}`,
        catalogList: (): string => '/catalog/list',
        catalogGraph: (): string => '/catalog/graph',
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
            sceneKey: 'CatalogProposals',
        },
    ],
}
