/**
 * Product manifest for ci_monitoring.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'CiMonitoring',
    scenes: {
        CIMonitoringDashboard: {
            name: 'CI monitoring',
            projectBased: true,
            import: () => import('./frontend/scenes/CIMonitoringDashboardScene'),
            iconType: 'ci_monitoring',
        },
        CIMonitoringTestDetail: {
            name: 'CI monitoring test',
            projectBased: true,
            import: () => import('./frontend/scenes/CIMonitoringTestDetailScene'),
            iconType: 'ci_monitoring',
        },
    },
    routes: {
        '/ci_monitoring': ['CIMonitoringDashboard', 'ciMonitoringDashboard'],
        '/ci_monitoring/tests/:testId': ['CIMonitoringTestDetail', 'ciMonitoringTestDetail'],
    },
    redirects: {},
    urls: {
        ciMonitoringDashboard: (): string => '/ci_monitoring',
        ciMonitoringTestDetail: (testId: string): string => `/ci_monitoring/tests/${testId}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'CI monitoring',
            intents: [ProductKey.CI_MONITORING],
            category: 'Unreleased',
            href: urls.ciMonitoringDashboard(),
            iconType: 'ci_monitoring' as FileSystemIconType,
            tags: ['alpha'],
            sceneKey: 'CIMonitoringDashboard',
        },
    ],
}
