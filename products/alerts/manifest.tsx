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
        alert: (alertId: string): string => `/alerts?alert_id=${alertId}`,
        alerts: (): string => '/alerts',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
