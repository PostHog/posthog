import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Dashboards v2',
    scenes: {
        DashboardV2: {
            name: 'Dashboard v2',
            import: () => import('./frontend/DashboardV2Scene'),
            projectBased: true,
        },
    },
    routes: {
        '/dashboard-v2': ['DashboardV2', 'dashboardV2'],
    },
    urls: {
        dashboardV2: (): string => '/dashboard-v2',
    },
}
