import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'AutoML',
    scenes: {
        AutoMLTasks: {
            name: 'AutoML',
            import: () => import('./frontend/scenes/AutoMLTasksScene'),
            projectBased: true,
            activityScope: 'AutoMLTask',
            description: 'Browse AutoML tasks, queries, and training runs.',
        },
        AutoMLTask: {
            name: 'AutoML task',
            import: () => import('./frontend/scenes/AutoMLTaskScene'),
            projectBased: true,
            activityScope: 'AutoMLTask',
        },
        AutoMLRun: {
            name: 'AutoML run',
            import: () => import('./frontend/scenes/AutoMLRunScene'),
            projectBased: true,
            activityScope: 'AutoMLTask',
        },
    },
    routes: {
        '/automl': ['AutoMLTasks', 'automlTasks'],
        '/automl/:name': ['AutoMLTask', 'automlTask'],
        '/automl/:name/runs/:runId': ['AutoMLRun', 'automlRun'],
    },
    redirects: {},
    urls: {
        automlTasks: (): string => '/automl',
        /** @param name Task name. ':name' for routing. */
        automlTask: (name: string): string => `/automl/${name}`,
        /** @param name Task name. ':name' for routing. @param runId Run id. ':runId' for routing. */
        automlRun: (name: string, runId: string): string => `/automl/${name}/runs/${runId}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
