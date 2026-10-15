import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Alerts',
    scenes: {
        Alerts: {
            import: () => import('./frontend/AlertsScene'),
            projectBased: true,
            name: 'Alerts',
            iconType: 'inbox',
            description: 'Monitor insight metrics and get notified when conditions are met.',
        },
    },
    routes: {
        '/alerts': ['Alerts', 'alerts'],
    },
    urls: {
        alert: (alertId: string): string => `/alerts?alert_type=insights&alert_id=${alertId}`,
        alerts: (): string => '/alerts',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Alerts',
            intents: [ProductKey.ALERTS],
            category: ProductItemCategory.MONITORING,
            iconType: 'inbox' as FileSystemIconType,
            href: urls.alerts(),
            searchKeywords: ['notifications', 'thresholds', 'monitors', 'insight alerts', 'log alerts'],
            searchTabs: [
                { name: 'Insight alerts', href: `${urls.alerts()}?alert_type=insights` },
                { name: 'Log alerts', href: `${urls.alerts()}?alert_type=logs` },
            ],
            sceneKey: 'Alerts',
        },
    ],
}
