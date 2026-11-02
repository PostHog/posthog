/**
 * Product manifest for APM.
 *
 * The first surface is the Application observability services list, behind the product flag.
 * The anomaly detector in the backend stays a dependency of the logs, tracing, and metrics
 * products and has no surface of its own here yet.
 */
import { FEATURE_FLAGS } from 'lib/constants'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { FileSystemIconColor, ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'APM',
    scenes: {
        ApplicationObservability: {
            name: 'Application observability',
            import: () => import('./frontend/ApplicationObservabilityScene'),
            projectBased: true,
            layout: 'app-container',
            activityScope: 'Tracing',
            description: 'Whether your application is OK, one row per service, from the signals you already send.',
            iconType: 'tracing',
        },
    },
    routes: {
        '/application-observability': ['ApplicationObservability', 'applicationObservability'],
    },
    redirects: {},
    urls: {
        applicationObservability: (): string => '/application-observability',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Application observability',
            intents: [ProductKey.TRACING],
            category: ProductItemCategory.MONITORING,
            iconType: 'tracing' as FileSystemIconType,
            iconColor: [
                'var(--color-product-tracing-light)',
                'var(--color-product-tracing-dark)',
            ] as FileSystemIconColor,
            href: '/application-observability',
            flag: FEATURE_FLAGS.APPLICATION_OBSERVABILITY,
            sceneKey: 'ApplicationObservability',
        },
    ],
}
