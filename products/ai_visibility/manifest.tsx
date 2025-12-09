import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'AI Visibility',
    scenes: {
        Viz: {
            name: 'Viz',
            import: () => import('./frontend/Viz'),
            allowUnauthenticated: true,
            layout: 'plain',
        },
    },
    routes: {
        '/viz/:domain': ['Viz', 'viz'],
    },
    redirects: {},
    urls: {},
}
