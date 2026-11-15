/**
 * Product manifest for access_control.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { ActivityScope, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'AccessControl',
    activityDescribers: {
        [ActivityScope.ACCESS_CONTROL]: () =>
            import('~/layout/navigation-3000/sidepanel/panels/access_control/accessControlActivityDescriber').then(
                (module) => module.accessControlActivityDescriber
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
