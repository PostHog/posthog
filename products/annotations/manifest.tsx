/**
 * Product manifest for annotations.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { AnnotationType, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Annotations',
    scenes: {
        Annotations: {
            name: 'Annotations',
            import: () => import('./frontend/pages/Annotations'),
            projectBased: true,
            description:
                'Annotations allow you to mark when certain changes happened so you can easily see how they impacted your metrics.',
            iconType: 'annotation',
        },
    },
    routes: {
        '/data-management/annotations': ['Annotations', 'annotations'],
        '/data-management/annotations/:id': ['Annotations', 'annotation'],
    },
    redirects: {},
    urls: {
        annotations: (): string => '/data-management/annotations',
        annotation: (id: AnnotationType['id'] | ':id'): string => `/data-management/annotations/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
