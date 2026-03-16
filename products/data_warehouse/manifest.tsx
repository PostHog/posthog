import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Data ops',
    scenes: {
        DataOps: {
            name: 'Data ops',
            import: () => import('./DataWarehouseScene'),
            projectBased: true,
            defaultDocsPath: '/docs/data-warehouse',
            activityScope: 'DataWarehouse',
            description:
                'Manage your data warehouse sources and queries. New source syncs are always free for the first 7 days',
            iconType: 'data_warehouse',
        },
        Models: {
            name: 'Models',
            import: () => import('../../frontend/src/scenes/models/ModelsScene'),
            projectBased: true,
            defaultDocsPath: '/docs/data-warehouse',
            description: 'Create and manage views and materialized views for transforming and organizing your data.',
            iconType: 'sql_editor',
        },
        NodeDetail: {
            name: 'Model detail',
            import: () => import('../../frontend/src/scenes/models/NodeDetailScene'),
            projectBased: true,
            defaultDocsPath: '/docs/data-warehouse',
        },
        SQLEditor: {
            projectBased: true,
            name: 'SQL editor',
            defaultDocsPath: '/docs/cdp/sources',
            layout: 'app-raw-no-header',
            hideProjectNotice: true,
            description: 'Write and execute SQL queries against your data warehouse',
        },
    },
    routes: {
        '/data-ops': ['DataOps', 'dataOps'],
        '/models': ['Models', 'models'],
        '/models/:id': ['NodeDetail', 'nodeDetail'],
    },
    urls: {
        dataOps: (tab?: string): string => (tab ? `/data-warehouse?tab=${tab}` : '/data-ops'),
        models: (): string => '/models',
        nodeDetail: (id: string): string => `/models/${id}`,
    },
    treeItemsProducts: [
        {
            path: 'SQL editor',
            intents: [ProductKey.DATA_WAREHOUSE_SAVED_QUERY, ProductKey.DATA_WAREHOUSE],
            category: 'Analytics',
            type: 'sql',
            iconType: 'sql_editor',
            iconColor: ['var(--color-product-data-warehouse-light)'],
            href: urls.sqlEditor(),
            sceneKey: 'SQLEditor',
            sceneKeys: ['SQLEditor'],
        },
        {
            path: 'Data warehouse',
            displayLabel: 'Data ops',
            intents: [ProductKey.DATA_WAREHOUSE, ProductKey.DATA_WAREHOUSE_SAVED_QUERY],
            category: 'Unreleased',
            href: urls.dataOps(),
            flag: FEATURE_FLAGS.DATA_WAREHOUSE_SCENE,
            iconType: 'data_warehouse',
            iconColor: ['var(--color-product-data-warehouse-light)'],
            sceneKey: 'DataOps',
        },
    ],
    treeItemsMetadata: [
        {
            path: `Sources`,
            category: 'Pipeline',
            type: 'hog_function/source',
            iconType: 'data_pipeline_metadata',
            href: urls.sources(),
            sceneKey: 'Sources',
            sceneKeys: ['Sources'],
        },
        {
            path: 'Models',
            category: 'Tools',
            type: 'sql',
            iconType: 'sql_editor',
            iconColor: ['var(--color-product-data-warehouse-light)'],
            href: urls.models(),
            sceneKey: 'Models',
            sceneKeys: ['Models'],
        },
        {
            path: 'Managed viewsets',
            category: 'Unreleased',
            iconType: 'managed_viewsets',
            href: urls.dataWarehouseManagedViewsets(),
            flag: FEATURE_FLAGS.MANAGED_VIEWSETS,
        },
    ],
}
