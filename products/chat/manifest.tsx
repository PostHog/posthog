import { IconChat } from '@posthog/icons'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Chat',
    scenes: {
        ChatList: {
            name: 'Chat List',
            import: () => import('./frontend/scenes/ChatList'),
            projectBased: true,
            defaultDocsPath: '/docs/feature-flags/early-access-feature-management',
            activityScope: 'ChatList',
        },
        Chat: {
            name: 'Chat',
            import: () => import('./frontend/scenes/Chat'),
            projectBased: true,
            defaultDocsPath: '/docs/feature-flags/early-access-feature-management',
            activityScope: 'Chat',
        },
        ChatSettings: {
            name: 'Chat Settings',
            import: () => import('./frontend/scenes/ChatSettings'),
            projectBased: true,
            defaultDocsPath: '/docs/feature-flags/early-access-feature-management',
            activityScope: 'ChatSettings',
        },
    },
    routes: {
        '/chat': ['ChatList', 'chatList'],
        '/chat/settings': ['ChatSettings', 'chatSettings'],
        '/chat/:id': ['Chat', 'chat'],
    },
    redirects: {},
    urls: {
        chatList: (): string => '/chat',
        chatSettings: (): string => '/chat/settings',
        chat:
            /** @param id A UUID or 'new'. ':id' for routing. */
            (id: string): string => `/chat/${id}`,
    },
    fileSystemTypes: {
        chat_feature: {
            icon: <IconChat />,
            href: (ref: string) => urls.chat(ref),
        },
    },
    treeItemsNew: [
        {
            path: 'Chat',
            type: 'chat_feature',
            href: urls.chat('new'),
        },
    ],
    treeItemsProducts: [
        {
            path: 'Chat',
            type: 'chat_feature',
            href: urls.chatList(),
        },
    ],
    fileSystemFilterTypes: {
        chat_feature: { name: 'Chat' },
    },
}
