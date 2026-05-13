import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, FileSystemIconType, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Deployments',
    scenes: {
        Deployments: {
            import: () => import('./frontend/Deployments'),
            projectBased: true,
            name: 'Deployments',
            iconType: 'live',
            description: 'Build and ship your project site straight from PostHog.',
        },
        Deployment: {
            import: () => import('./frontend/Deployment'),
            projectBased: true,
            name: 'Deployment',
        },
    },
    routes: {
        '/deployments': ['Deployments', 'deployments'],
        '/deployments/:id': ['Deployment', 'deployment'],
    },
    urls: {
        deployments: (): string => '/deployments',
        deployment: (id: string): string => `/deployments/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Deployments',
            intents: [ProductKey.DEPLOYMENTS],
            category: ProductItemCategory.TOOLS,
            href: urls.deployments(),
            type: 'live',
            iconType: 'live' as FileSystemIconType,
            iconColor: ['var(--color-text-3000)'] as FileSystemIconColor,
            sceneKey: 'Deployments',
            sceneKeys: ['Deployments', 'Deployment'],
        },
    ],
}
