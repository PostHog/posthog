/**
 * Product manifest for APM.
 *
 * APM presents logs, tracing, and metrics as three facets of one product. The facet scenes stay
 * registered in their own products and keep their own nav entries; this manifest adds the unified
 * shell on top, gated on `UNIFIED_APM_PRODUCT` until it replaces them.
 */
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'APM',
    scenes: {
        APM: {
            name: 'APM',
            import: () => import('./frontend/ApmScene'),
            projectBased: true,
            layout: 'app-container',
            description: 'Monitor logs, traces, and metrics for your services in one place.',
            iconType: 'tracing',
        },
    },
    routes: {
        '/apm': ['APM', 'apm'],
    },
    redirects: {},
    urls: {
        apm: (tab?: string): string => (tab ? `/apm?tab=${tab}` : '/apm'),
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'APM',
            // Reuses the three facet product keys rather than minting a new one: APM is the shell
            // over them, so interest in any facet is interest in APM.
            intents: [ProductKey.LOGS, ProductKey.TRACING, ProductKey.METRICS],
            category: ProductItemCategory.APP_MONITORING,
            iconType: 'tracing',
            iconColor: [
                'var(--color-product-tracing-light)',
                'var(--color-product-tracing-dark)',
            ] as FileSystemIconColor,
            href: urls.apm(),
            flag: FEATURE_FLAGS.UNIFIED_APM_PRODUCT,
            tags: ['alpha'],
            sceneKey: 'APM',
        },
    ],
}
