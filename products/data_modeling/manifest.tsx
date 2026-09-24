import { urls } from 'scenes/urls'

import { ProductManifest } from '~/types'

import type { ModelsSceneTab } from './frontend/modelsSceneLogic'
import type { NodeDetailSceneTab } from './frontend/nodeDetail/nodeDetailSceneLogic'

export const manifest: ProductManifest = {
    name: 'Data modeling',
    scenes: {
        Models: {
            name: 'Models',
            import: () => import('./frontend/ModelsScene'),
            projectBased: true,
            description: 'Create and manage views and materialized views for transforming and organizing your data.',
            iconType: 'sql_editor',
        },
        NodeDetail: {
            name: 'Model detail',
            import: () => import('./frontend/nodeDetail/NodeDetailScene'),
            projectBased: true,
        },
    },
    routes: {
        '/models': ['Models', 'models'],
        '/models/:id': ['NodeDetail', 'nodeDetail'],
        '/models/:id/:tab': ['NodeDetail', 'nodeDetail'],
    },
    urls: {
        models: (tab?: ModelsSceneTab): string => (tab && tab !== 'overview' ? `/models?tab=${tab}` : '/models'),
        nodeDetail: (id: string, tab?: NodeDetailSceneTab): string => `/models/${id}${tab ? `/${tab}` : ''}`,
    },
    treeItemsMetadata: [
        {
            path: 'Models',
            category: 'Tools',
            type: 'sql',
            iconType: 'sql_editor',
            iconColor: ['var(--color-product-data-warehouse-light)'],
            href: urls.models(),
            sceneKey: 'Models',
            sceneKeys: ['Models'],
        },
    ],
}
