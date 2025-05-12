import { IconRocket } from '@posthog/icons'
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
            icon: <IconRocket />,
            href: (ref: string) => urls.action(ref),
        },
    },
    fileSystemFilterTypes: {
        action: { name: 'Actions' },
    },
    treeItemsNew: [
        {
            type: 'action',
            path: 'Action',
            href: urls.createAction(),
        },
    ],
}
