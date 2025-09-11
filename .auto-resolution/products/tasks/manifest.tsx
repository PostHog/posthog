import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Tasks',
    scenes: {
        TaskTracker: {
            name: 'Tasks',
            import: () => import('./frontend/TaskTracker'),
            projectBased: true,
            defaultDocsPath: '/docs/tasks',
            activityScope: 'TaskTracker',
        },
    },
    routes: {
        '/tasks': ['TaskTracker', 'taskTracker'],
    },
    redirects: {},
    urls: {
        taskTracker: (): string => '/tasks',
    },
    fileSystemTypes: {
        task: {
            name: 'Task',
            iconType: 'task',
            href: () => urls.taskTracker(),
            iconColor: ['var(--product-tasks-light)', 'var(--product-tasks-dark)'],
            filterKey: 'task',
            flag: FEATURE_FLAGS.TASKS,
        },
    },
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Tasks',
            category: 'Development',
            type: 'task',
            href: urls.taskTracker(),
            flag: FEATURE_FLAGS.TASKS,
            iconType: 'task',
            iconColor: ['var(--product-tasks-light)', 'var(--product-tasks-dark)'] as FileSystemIconColor,
        },
    ],
}
