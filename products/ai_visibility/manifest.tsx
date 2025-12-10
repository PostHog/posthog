import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'AI visibility',
    scenes: {
        Viz: {
            name: 'AI visibility',
            import: () => import('./frontend/VizScene'),
            allowUnauthenticated: true,
            layout: 'plain',
        },
    },
    routes: {
        '/viz/:brand': ['Viz', 'viz'],
    },
    redirects: {
        '/viz': '/viz/posthog',
    },
    urls: {
        viz: (brand: string): string => `/viz/${brand}`,
    },
}
