import { IconCursor } from '@posthog/icons'
import { urls } from 'scenes/urls'

import { ActionType, ProductManifest } from '../../frontend/src/types'

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
    fileSystemTypes: {
        action: {
            name: 'Action',
            icon: <IconCursor />,
            href: (ref: string) => urls.action(ref),
            filterKey: 'action',
        },
    },
    treeItemsNew: [
        {
            type: 'action',
            path: 'Action',
            href: urls.createAction(),
        },
    ],
    treeItemsMetadata: [
        {
            path: 'Actions',
            category: 'Definitions',
            iconType: 'rocket',
            href: urls.actions(),
        },
    ],
}
