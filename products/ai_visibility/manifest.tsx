import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Tasks',
    scenes: {
        Viz: {
            name: 'Viz',
            import: () => import('./frontend/Viz'),
            allowUnauthenticated: true,
            layout: 'plain',
        },
    },
    routes: {
        '/viz': ['Viz', 'viz'],
    },
    redirects: {},
    urls: {},
}
