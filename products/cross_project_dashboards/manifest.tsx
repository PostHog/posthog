import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'CrossProjectDashboards',
    scenes: {
        CrossProjectDashboards: {
            name: 'Cross-project dashboards',
            import: () => import('./frontend/CrossProjectDashboardsScene'),
            // Organization-scoped, not project-scoped: a dashboard here holds insights from
            // several projects, so it cannot live under /project/:id.
            organizationBased: true,
            activityScope: 'CrossProjectDashboard',
            description: 'Put insights from several projects on one page.',
        },
        CrossProjectDashboard: {
            name: 'Cross-project dashboard',
            import: () => import('./frontend/CrossProjectDashboardScene'),
            organizationBased: true,
            activityScope: 'CrossProjectDashboard',
        },
    },
    routes: {
        '/cross-project-dashboards': ['CrossProjectDashboards', 'crossProjectDashboards'],
        '/cross-project-dashboards/:id': ['CrossProjectDashboard', 'crossProjectDashboard'],
    },
    redirects: {},
    urls: {
        crossProjectDashboards: (): string => '/cross-project-dashboards',
        crossProjectDashboard: (id: string): string => `/cross-project-dashboards/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
