import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'DashboardsV2',
    scenes: {
        DashboardsV2: {
            name: 'Dashboards',
            import: () => import('./frontend/list/DashboardV2ListScene'),
            projectBased: true,
        },
        DashboardV2: {
            name: 'Dashboard',
            import: () => import('./frontend/dashboard/DashboardV2Scene'),
            projectBased: true,
        },
    },
    routes: {
        '/d': ['DashboardsV2', 'dashboardsV2'],
        '/d/:uid': ['DashboardV2', 'dashboardV2'],
    },
    redirects: {},
    urls: {
        dashboardsV2: (): string => '/d',
        dashboardV2: (uid: string): string => `/d/${uid}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
