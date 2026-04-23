import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope, ProductManifest } from '~/types'

import type { SourceSceneTab } from './frontend/scenes/SourceScene/SourceScene'

export const manifest: ProductManifest = {
    name: 'Data ops',
    scenes: {
        DataOps: {
            name: 'Data ops',
            import: () => import('./DataWarehouseScene'),
            projectBased: true,
            activityScope: 'DataWarehouse',
            description:
                'Manage your data warehouse sources and queries. New source syncs are always free for the first 7 days',
            iconType: 'data_warehouse',
        },
        Models: {
            name: 'Models',
            import: () => import('../../frontend/src/scenes/models/ModelsScene'),
            projectBased: true,
            description: 'Create and manage views and materialized views for transforming and organizing your data.',
            iconType: 'sql_editor',
        },
        NodeDetail: {
            name: 'Model detail',
            import: () => import('../../frontend/src/scenes/models/NodeDetailScene'),
            projectBased: true,
        },
        SQLEditor: {
            projectBased: true,
            name: 'SQL editor',
            layout: 'app-raw-no-header',
            hideProjectNotice: true,
            description: 'Write and execute SQL queries against your data warehouse',
        },
        Sources: {
            import: () => import('./frontend/scenes/SourcesScene/SourcesScene'),
            projectBased: true,
            name: 'Sources',
            description:
                'Import data into PostHog from external sources including webhooks, application connectors, and self-managed databases.',
            activityScope: ActivityScope.HOG_FUNCTION,
            iconType: 'data_pipeline',
        },
        DataWarehouseSource: {
            import: () => import('./frontend/scenes/SourceScene/SourceScene'),
            projectBased: true,
            name: 'Data warehouse source',
        },
        DataWarehouseSourceNew: {
            import: () => import('./frontend/scenes/NewSourceScene/NewSourceScene'),
            projectBased: true,
            name: 'New data warehouse source',
        },
    },
    routes: {
        '/data-ops': ['DataOps', 'dataOps'],
        '/models': ['Models', 'models'],
        '/models/:id': ['NodeDetail', 'nodeDetail'],
        '/data-management/sources': ['Sources', 'sources'],
        '/data-management/sources/:id/:tab': ['DataWarehouseSource', 'dataWarehouseSource'],
        '/data-warehouse/new-source': ['DataWarehouseSourceNew', 'dataWarehouseSourceNew'],
    },
    redirects: {
        '/data-warehouse/sources/:id': ({ id }) => urls.dataWarehouseSource(id, 'schemas'),
        '/data-warehouse/sources/:id/:tab': ({ id, tab }) => urls.dataWarehouseSource(id, tab as SourceSceneTab),
    },
    urls: {
        dataOps: (tab?: string): string => (tab ? `/data-warehouse?tab=${tab}` : '/data-ops'),
        models: (): string => '/models',
        nodeDetail: (id: string): string => `/models/${id}`,
        sources: (): string => '/data-management/sources',
        dataWarehouseSource: (id: string, tab?: SourceSceneTab): string =>
            `/data-management/sources/${id}/${tab ?? 'schemas'}`,
        dataWarehouseSourceNew: (
            kind?: string,
            returnUrl?: string,
            returnLabel?: string,
            accessMethod?: 'warehouse' | 'direct'
        ): string => {
            const params = new URLSearchParams()
            if (kind) {
                params.set('kind', kind)
            }
            if (returnUrl) {
                params.set('returnUrl', returnUrl)
            }
            if (returnLabel) {
                params.set('returnLabel', returnLabel)
            }
            if (accessMethod) {
                params.set('access_method', accessMethod)
            }
            const queryString = params.toString()
            return `/data-warehouse/new-source${queryString ? `?${queryString}` : ''}`
        },
    },
    treeItemsProducts: [
        {
            path: 'SQL editor',
            intents: [ProductKey.DATA_WAREHOUSE_SAVED_QUERY, ProductKey.DATA_WAREHOUSE],
            category: ProductItemCategory.ANALYTICS,
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
            category: ProductItemCategory.UNRELEASED,
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
