import { FEATURE_FLAGS } from 'lib/constants'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Semantic layer',
    scenes: {
        CatalogProposals: {
            import: () => import('./frontend/CatalogProposalsScene'),
            projectBased: true,
            name: 'Inbox',
            activityScope: 'CatalogNode',
            layout: 'app-container',
            iconType: 'data_warehouse',
        },
        CatalogList: {
            import: () => import('./frontend/CatalogListScene'),
            projectBased: true,
            name: 'Semantic layer',
            activityScope: 'CatalogNode',
            layout: 'app-container',
            iconType: 'data_warehouse',
        },
        CatalogGraph: {
            import: () => import('./frontend/CatalogGraphScene'),
            projectBased: true,
            name: 'Lineage',
            activityScope: 'CatalogNode',
            layout: 'app-container',
            iconType: 'data_warehouse',
        },
        CatalogDefinition: {
            import: () => import('./frontend/CatalogDefinitionScene'),
            projectBased: true,
            name: 'Node',
            activityScope: 'CatalogNode',
            layout: 'app-container',
            iconType: 'data_warehouse',
        },
        CatalogLogs: {
            import: () => import('./frontend/CatalogLogsScene'),
            projectBased: true,
            name: 'Logs',
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
        '/catalog/logs': ['CatalogLogs', 'catalogLogs'],
        '/catalog/definitions/:id': ['CatalogDefinition', 'catalogDefinition'],
    },
    urls: {
        catalog: (): string => '/catalog',
        catalogProposal: (id: string): string => `/catalog/proposals/${id}`,
        catalogList: (): string => '/catalog/list',
        catalogGraph: (): string => '/catalog/graph',
        catalogLogs: (): string => '/catalog/logs',
        catalogDefinition: (id: string): string => `/catalog/definitions/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Semantic layer',
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
