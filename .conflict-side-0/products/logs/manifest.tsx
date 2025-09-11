import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Logs',
    scenes: {
        Logs: {
            import: () => import('./frontend/LogsScene'),
            projectBased: true,
            name: 'Logs',
            activityScope: 'Logs',
            layout: 'app-container',
        },
    },
    routes: {
        '/logs': ['Logs', 'logs'],
    },
    redirects: {},
    urls: { logs: (): string => '/logs' },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Logs',
            category: 'Tools',
            iconType: 'logs' as FileSystemIconType,
            iconColor: ['var(--color-product-logs-light)'] as FileSystemIconColor,
            href: urls.logs(),
            flag: FEATURE_FLAGS.LOGS,
            tags: ['alpha'],
        },
    ],
}
