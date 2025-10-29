import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

import { ActionType, FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Actions',
    urls: {
        createAction: (): string => `/data-management/actions/new`,
        duplicateAction: (action: ActionType | null): string => {
            const queryParams = action ? `?copy=${encodeURIComponent(JSON.stringify(action))}` : ''
            return `/data-management/actions/new/${queryParams}`
        },
        action: (id: string | number): string => `/data-management/actions/${id}`,
        actions: (): string => '/data-management/actions',
    },
    scenes: {
        Actions: {
            name: 'Actions',
            import: () => import('./frontend/pages/Actions'),
            projectBased: true,
            defaultDocsPath: '/docs/data/actions',
            activityScope: 'Action',
            description:
                'Combine several related events into one, which you can then analyze in insights and dashboards as if it were a single event.',
            iconType: 'action',
        },
        Action: {
            name: 'Action',
            import: () => import('./frontend/pages/Action'),
            projectBased: true,
            defaultDocsPath: '/docs/data/actions',
            activityScope: 'Action',
            iconType: 'action',
        },
        NewAction: {
            name: 'New Action',
            import: () => import('./frontend/pages/Action'),
            projectBased: true,
            defaultDocsPath: '/docs/data/actions',
            activityScope: 'Action',
            iconType: 'action',
        },
    },
    routes: {
        '/data-management/actions': ['Actions', 'actions'],
        '/data-management/actions/new': ['NewAction', 'actionNew'],
        '/data-management/actions/:id': ['Action', 'action'],
        '/data-management/actions/new/': ['NewAction', 'actionNew'],
    },
    fileSystemTypes: {
        action: {
            name: 'Action',
            href: (ref: string) => urls.action(ref),
            filterKey: 'action',
            iconType: 'action' as FileSystemIconType,
            iconColor: ['var(--color-product-actions-light)'] as FileSystemIconColor,
        },
    },
    treeItemsNew: [
        {
            type: 'action',
            path: 'Action',
            href: urls.createAction(),
            iconType: 'action' as FileSystemIconType,
            iconColor: ['var(--color-product-actions-light)'] as FileSystemIconColor,
        },
    ],
    treeItemsMetadata: [
        {
            path: 'Actions',
            category: 'Schema',
            href: urls.actions(),
            iconType: 'action' as FileSystemIconType,
            sceneKey: 'Actions',
        },
    ],
}
