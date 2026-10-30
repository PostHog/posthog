import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'AlertsPlatform',
    scenes: {
        PlatformAlerts: {
            name: 'Platform alerts',
            description:
                'Get told when your logs or data cross a threshold you set, in Slack, email, PagerDuty, or another tool.',
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
    treeItemsProducts: [
        {
            path: 'Platform alerts',
            intents: [],
            category: ProductItemCategory.UNRELEASED,
            iconType: 'inbox',
            href: urls.platformAlerts(),
            searchKeywords: ['alerts', 'alerting', 'notifications', 'monitors'],
            flag: FEATURE_FLAGS.PLATFORM_ALERTS,
            sceneKey: 'PlatformAlerts',
            sceneKeys: ['PlatformAlerts', 'PlatformAlert'],
        },
    ],
}
