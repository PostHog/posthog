import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Dashboards v2',
    scenes: {
        DashboardV2: {
            name: 'Dashboard v2',
            import: () => import('./frontend/scene/DashboardScene'),
            projectBased: true,
        },
    },
    routes: {
        '/dashboard-v2': ['DashboardV2', 'dashboardV2'],
        '/dashboard-v2/:uid': ['DashboardV2', 'dashboardV2'],
    },
    urls: {
        dashboardV2: (uid?: string): string => (uid ? `/dashboard-v2/${encodeURIComponent(uid)}` : '/dashboard-v2'),
    },
}
