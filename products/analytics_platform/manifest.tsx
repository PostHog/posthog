import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Analytics Platform',
    scenes: {
        ProductExplorer: {
            name: 'Product explorer',
            import: () => import('./frontend/ProductExplorer/ProductExplorer'),
            projectBased: true,
            layout: 'app-raw',
        },
    },
    routes: {
        '/products/explorer': ['ProductExplorer', 'productExplorer'],
    },
    urls: {
        productExplorer: (): string => '/products/explorer',
    },
}
