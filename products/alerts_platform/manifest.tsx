import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'AlertsPlatform',
    scenes: {
        PlatformAlerts: {
            name: 'Platform alerts',
            import: () => import('./frontend/PlatformAlertsScene'),
            projectBased: true,
            iconType: 'inbox',
        },
        PlatformAlert: {
            name: 'Platform alert',
            import: () => import('./frontend/PlatformAlertScene'),
            projectBased: true,
            iconType: 'inbox',
        },
    },
    routes: {
        '/platform-alerts': ['PlatformAlerts', 'platformAlerts'],
        '/platform-alerts/:id': ['PlatformAlert', 'platformAlert'],
    },
    redirects: {},
    urls: {
        platformAlerts: (): string => '/platform-alerts',
        platformAlert: (id: string): string => `/platform-alerts/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
