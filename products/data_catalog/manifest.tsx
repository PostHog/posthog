import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { ActivityScope, ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'DataCatalog',
    activityDescribers: {
        [ActivityScope.EVENT_DEFINITION]: () =>
            import('scenes/data-management/dataManagementDescribers').then(
                (module) => module.dataManagementActivityDescriber
            ),
        [ActivityScope.PROPERTY_DEFINITION]: () =>
            import('scenes/data-management/dataManagementDescribers').then(
                (module) => module.dataManagementActivityDescriber
            ),
    },
    scenes: {
        DataCatalog: {
            import: () => import('./frontend/DataCatalogScene'),
            projectBased: true,
            name: 'Data catalog',
            layout: 'app-container',
            iconType: 'data_warehouse',
            description: 'Review and manage governed metrics, certifications, and relationships for your data.',
            docsHref: 'https://posthog.com/docs/semantic-layer',
        },
        DataCatalogMetric: {
            import: () => import('./frontend/DataCatalogMetricScene'),
            projectBased: true,
            name: 'Metric',
        },
        DataCatalogNewMetric: {
            import: () => import('./frontend/DataCatalogNewMetricScene'),
            projectBased: true,
            name: 'New metric',
        },
    },
    routes: {
        '/data-catalog': ['DataCatalog', 'dataCatalog'],
        '/data-catalog/metrics/:name': ['DataCatalogMetric', 'dataCatalogMetric'],
        '/data-catalog/new-metric': ['DataCatalogNewMetric', 'dataCatalogNewMetric'],
    },
    redirects: {},
    urls: {
        dataCatalog: (tab?: string): string => `/data-catalog${tab ? `?tab=${tab}` : ''}`,
        dataCatalogNewMetric: (): string => '/data-catalog/new-metric',
        dataCatalogMetric: (name: string, tab?: 'definition' | 'data-quality' | 'lineage'): string =>
            `/data-catalog/metrics/${name}${tab && tab !== 'definition' ? `?tab=${tab}` : ''}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Data catalog',
            intents: [ProductKey.DATA_CATALOG],
            category: ProductItemCategory.DATA,
            type: 'data_catalog',
            iconType: 'data_catalog',
            iconColor: ['var(--color-product-data-catalog-light)', 'var(--color-product-data-catalog-dark)'],
            href: urls.dataCatalog(),
            searchKeywords: ['semantic layer', 'metrics', 'data dictionary', 'glossary', 'governance'],
            searchTabs: [
                {
                    name: 'Tables & views',
                    href: urls.dataCatalog('tables'),
                    requiredFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE],
                    searchKeywords: [
                        'models',
                        'materialized views',
                        'materialization',
                        'data modeling',
                        'sql views',
                        'saved queries',
                    ],
                },
                {
                    name: 'Lineage',
                    href: urls.dataCatalog('lineage'),
                    requiredFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE],
                    searchKeywords: ['dag', 'dependencies'],
                },
                {
                    name: 'Data quality',
                    href: urls.dataCatalog('data-quality'),
                    requiredFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE],
                    searchKeywords: ['data tests', 'checks', 'freshness'],
                },
                {
                    name: 'Usage',
                    href: urls.dataCatalog('usage'),
                    requiredFlags: [
                        FEATURE_FLAGS.TODAY_RAIL_NAV,
                        FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE,
                        FEATURE_FLAGS.DATA_MODELING_USAGE,
                    ],
                    searchKeywords: ['bytes read', 'cpu'],
                },
                { name: 'Relationships', href: urls.dataCatalog('relationships') },
                { name: 'Certifications', href: urls.dataCatalog('certifications') },
            ],
            sceneKey: 'DataCatalog',
        },
    ],
}
