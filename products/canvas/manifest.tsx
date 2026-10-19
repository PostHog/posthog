import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Canvas',
    scenes: {
        CanvasNew: {
            name: 'New canvas',
            import: () => import('./frontend/newCanvas/CanvasNewScene'),
            projectBased: true,
            layout: 'app-raw',
        },
        Canvases: {
            name: 'Canvases',
            import: () => import('./frontend/list/CanvasesScene'),
            projectBased: true,
        },
        // `Canvas` and `urls.canvas` already belong to the notebooks canvas.
        CanvasDetail: {
            name: 'Canvas',
            import: () => import('./frontend/scene/CanvasScene'),
            projectBased: true,
            layout: 'app-raw',
        },
    },
    routes: {
        // Listed before `/canvases/:id`, so "new" never matches as a canvas id.
        '/canvases': ['Canvases', 'canvases'],
        '/canvases/new': ['CanvasNew', 'canvasNew'],
        '/canvases/:id': ['CanvasDetail', 'canvasDetail'],
    },
    redirects: {},
    urls: {
        canvases: (): string => '/canvases',
        canvasNew: (spaceId?: string | null): string =>
            spaceId ? `/canvases/new?space=${encodeURIComponent(spaceId)}` : '/canvases/new',
        canvasDetail: (id: string): string => `/canvases/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
