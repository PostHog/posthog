import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Analytics Platform',
    scenes: {
        PrecomputeDebug: {
            import: () => import('./frontend/PrecomputeDebugScene'),
            projectBased: true,
            name: 'Precompute debug',
            description: 'Staff-only view of stored precompute hashes, buckets, and TTLs.',
            layout: 'app-container',
            iconType: 'web_analytics',
        },
    },
    routes: {
        '/debug/precompute': ['PrecomputeDebug', 'precomputeDebug'],
    },
    urls: {
        precomputeDebug: (): string => `/debug/precompute`,
    },
}
