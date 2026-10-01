import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Canvas',
    scenes: {
        // `Canvas` and `urls.canvas` already belong to the notebooks canvas.
        CanvasDetail: {
            name: 'Canvas',
            import: () => import('./frontend/scene/CanvasScene'),
            projectBased: true,
            layout: 'app-full-scene-height',
        },
    },
    routes: {
        '/canvases/:id': ['CanvasDetail', 'canvasDetail'],
    },
    redirects: {},
    urls: {
        canvasDetail: (id: string): string => `/canvases/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
