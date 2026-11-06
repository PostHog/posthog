/**
 * Product manifest for batch_exports.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { ActivityScope, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'BatchExports',
    activityDescribers: {
        [ActivityScope.BATCH_EXPORT]: () =>
            import('scenes/data-pipelines/batch-exports/activityDescriptions').then(
                (module) => module.batchExportActivityDescriber
            ),
        [ActivityScope.BATCH_IMPORT]: () =>
            import('scenes/data-pipelines/batch-imports/activityDescriptions').then(
                (module) => module.batchImportActivityDescriber
            ),
    },
    scenes: {
        // Define scenes here
    },
    routes: {
        // Define routes here
    },
    redirects: {},
    urls: {
        // Define URL helpers here
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
