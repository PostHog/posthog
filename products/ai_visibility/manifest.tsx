import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Tasks',
    scenes: {
        Viz: {
            name: 'Viz',
            import: () => import('./frontend/Viz'),
            projectBased: true,
            defaultDocsPath: '/docs/tasks',
            activityScope: 'TaskTracker',
            description: 'Tasks are work that agents can do for you, like creating a pull request or fixing an issue.',
            iconType: 'task',
        },
    },
    routes: {
        '/viz': ['Viz', 'viz'],
    },
    redirects: {},
    urls: {
        taskTracker: (): string => '/viz',
    },
}
