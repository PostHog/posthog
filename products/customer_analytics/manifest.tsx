import { combineUrl } from 'kea-router'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { FileSystemIconColor, ProductManifest } from '~/types'

import type { WarehousePropertiesSceneTab } from './frontend/scenes/WarehousePropertiesScene/warehousePropertiesSceneLogic'

export const manifest: ProductManifest = {
    name: 'Customer analytics',
    scenes: {
        CustomerAnalytics: {
            import: () => import('./frontend/CustomerAnalyticsScene'),
            projectBased: true,
            name: 'Customer analytics',
            description: 'Understand how your customers interact with your product ',
            iconType: 'cohort',
            docsHref: 'https://posthog.com/docs/customer-analytics',
        },
        CustomerAnalyticsAccount: {
            import: () => import('./frontend/scenes/CustomerAnalyticsAccountScene/CustomerAnalyticsAccountScene'),
            projectBased: true,
            name: 'Account details',
            iconType: 'cohort',
            layout: 'app-full-scene-height',
        },
        CustomerAnalyticsConfiguration: {
            import: () =>
                import('./frontend/scenes/CustomerAnalyticsConfigurationScene/CustomerAnalyticsConfigurationScene'),
            projectBased: true,
            name: 'Customer analytics configuration',
        },
        CustomerJourneyBuilder: {
            import: () => import('./frontend/scenes/CustomerJourneyBuilderScene/CustomerJourneyBuilderScene'),
            projectBased: true,
            name: 'New journey',
        },
        CustomerJourneyTemplates: {
            import: () => import('./frontend/scenes/CustomerJourneyTemplatesScene/CustomerJourneyTemplatesScene'),
            projectBased: true,
            name: 'New journey',
        },
        WarehouseProperties: {
            import: () => import('./frontend/scenes/WarehousePropertiesScene/WarehousePropertiesScene'),
            projectBased: true,
            name: 'Warehouse properties',
            description: 'Add properties to your people and groups from a data warehouse table.',
            iconType: 'data_warehouse',
        },
    },
    routes: {
        '/customer_analytics/dashboard': ['CustomerAnalytics', 'customerAnalyticsDashboard'],
        '/customer_analytics/accounts': ['CustomerAnalytics', 'customerAnalyticsAccounts'],
        // The detail scene serves these paths behind its flag and falls back to the list for legacy deep links.
        '/customer_analytics/accounts/:accountId': ['CustomerAnalyticsAccount', 'customerAnalyticsAccount'],
        '/customer_analytics/accounts/:accountId/:tab': ['CustomerAnalyticsAccount', 'customerAnalyticsAccount'],
        '/customer_analytics/notes': ['CustomerAnalytics', 'customerAnalyticsNotes'],
        '/customer_analytics/announcements': ['CustomerAnalytics', 'customerAnalyticsAnnouncements'],
        '/customer_analytics/feed': ['CustomerAnalytics', 'customerAnalyticsFeed'],
        '/customer_analytics/feature-requests': ['CustomerAnalytics', 'customerAnalyticsFeatureRequests'],
        '/customer_analytics/feature-requests/:requestId': ['CustomerAnalytics', 'customerAnalyticsFeatureRequests'],
        '/customer_analytics/journeys/new': ['CustomerJourneyBuilder', 'customerJourneyBuilder'],
        '/customer_analytics/journeys/templates': ['CustomerJourneyTemplates', 'customerJourneyTemplates'],
        '/customer_analytics/journeys/:id/edit': ['CustomerJourneyBuilder', 'customerJourneyEdit'],
        '/customer_analytics/journeys': ['CustomerAnalytics', 'customerAnalyticsJourneys'],
        '/customer_analytics/configuration': ['CustomerAnalyticsConfiguration', 'customerAnalyticsConfiguration'],
        '/data-management/warehouse-properties': ['WarehouseProperties', 'warehouseProperties'],
        '/data-management/warehouse-properties/:tab': ['WarehouseProperties', 'warehouseProperties'],
    },
    redirects: {
        '/customer_analytics': (_params, searchParams, hashParams) => {
            const defaultTab = posthog.getFeatureFlag(FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP)
                ? '/customer_analytics/accounts'
                : '/customer_analytics/dashboard'
            return combineUrl(defaultTab, searchParams, hashParams).url
        },
    },
    urls: {
        customerAnalytics: (): string => '/customer_analytics',
        customerAnalyticsDashboard: (): string => '/customer_analytics/dashboard',
        customerAnalyticsAccounts: (): string => '/customer_analytics/accounts',
        // Account detail path. The flag-off scene falls back to the filtered, expanded Accounts list.
        customerAnalyticsAccount: (accountId: string, tab?: string): string =>
            `/customer_analytics/accounts/${accountId}${tab ? `/${tab}` : ''}`,
        customerAnalyticsNotes: (): string => '/customer_analytics/notes',
        customerAnalyticsAnnouncements: (): string => '/customer_analytics/announcements',
        customerAnalyticsFeed: (): string => '/customer_analytics/feed',
        customerAnalyticsFeatureRequests: (requestId?: string): string =>
            `/customer_analytics/feature-requests${requestId ? `/${requestId}` : ''}`,
        customerAnalyticsJourneys: (): string => '/customer_analytics/journeys',
        customerAnalyticsConfiguration: (tab?: string): string =>
            `/customer_analytics/configuration${tab ? `?tab=${tab}` : ''}`,
        customerJourneyBuilder: (): string => '/customer_analytics/journeys/new',
        customerJourneyTemplates: (): string => '/customer_analytics/journeys/templates',
        customerJourneyEdit: (id: string): string => `/customer_analytics/journeys/${id}/edit`,
        warehouseProperties: (tab?: WarehousePropertiesSceneTab): string =>
            `/data-management/warehouse-properties${tab ? `/${tab}` : ''}`,
    },
    treeItemsProducts: [
        {
            path: 'Customer analytics',
            intents: [ProductKey.CUSTOMER_ANALYTICS],
            category: ProductItemCategory.ANALYTICS,
            iconType: 'cohort',
            iconColor: [
                'var(--color-product-customer-analytics-light)',
                'var(--color-product-customer-analytics-dark)',
            ] as FileSystemIconColor,
            href: urls.customerAnalytics(),
            tags: ['beta'],
            flag: FEATURE_FLAGS.CUSTOMER_ANALYTICS,
            sceneKey: 'CustomerAnalytics',
            sceneKeys: [
                'CustomerAnalytics',
                'CustomerAnalyticsAccount',
                'CustomerJourneyTemplates',
                'CustomerJourneyBuilder',
            ],
        },
    ],
    // Deliberately not behind the Customer analytics flag: warehouse-backed person and group
    // properties are useful without opting into Customer analytics, so this is their home in Data.
    treeItemsMetadata: [
        {
            path: 'Warehouse properties',
            category: 'Schema',
            iconType: 'data_warehouse',
            href: urls.warehouseProperties(),
            flag: FEATURE_FLAGS.WAREHOUSE_PERSON_PROPERTIES,
            sceneKey: 'WarehouseProperties',
            sceneKeys: ['WarehouseProperties'],
        },
    ],
}
