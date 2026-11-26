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
        // pinned: URL path, as bookmarks and shared links name boards by it
        '/dashboard-v2/:uid': ['DashboardV2', 'dashboardV2Board'],
    },
    urls: {
        dashboardV2: (): string => '/dashboard-v2',
        dashboardV2Board: (uid: string): string => `/dashboard-v2/${uid}`,
    },
}
