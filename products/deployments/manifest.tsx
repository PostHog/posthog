import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Deployments',
    scenes: {
        Deployments: {
            import: () => import('./frontend/Deployments'),
            projectBased: true,
            name: 'Deployments',
            iconType: 'deployments',
            description: 'View, redeploy, and roll back deployments of your app.',
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
    fileSystemTypes: {
        deployments: {
            name: 'Deployment',
            iconType: 'deployments',
            iconColor: ['var(--color-product-deployments-light)'] as FileSystemIconColor,
            href: () => urls.deployments(),
            filterKey: 'deployments',
        },
    },
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Deployments',
            intents: [ProductKey.DEPLOYMENTS],
            category: ProductItemCategory.TOOLS,
            href: urls.deployments(),
            type: 'deployments',
            iconType: 'deployments' as FileSystemIconType,
            iconColor: [
                'var(--color-product-deployments-light)',
                'var(--color-product-deployments-dark)',
            ] as FileSystemIconColor,
            sceneKey: 'Deployments',
            sceneKeys: ['Deployments', 'Deployment'],
            flag: FEATURE_FLAGS.DEPLOYMENTS,
            tags: ['alpha'],
        },
    ],
}
