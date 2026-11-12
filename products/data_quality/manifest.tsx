import { ActivityScope, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'DataQuality',
    activityDescribers: {
        [ActivityScope.DATA_QUALITY_CHECK]: () =>
            import('./frontend/activityDescriber').then((module) => module.dataQualityCheckActivityDescriber),
        [ActivityScope.DATA_QUALITY_CHECK_SCHEDULE]: () =>
            import('./frontend/activityDescriber').then((module) => module.dataQualityCheckScheduleActivityDescriber),
    },
    scenes: {},
    routes: {},
    redirects: {},
    urls: {},
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
    treeItemsMetadata: [],
}
