import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Conversations',
    scenes: {
        ConversationsTickets: {
            name: 'Ticket list',
            import: () => import('./frontend/scenes/tickets/ConversationsTicketsScene'),
            projectBased: true,
            layout: 'app-container',
        },
        ConversationsTicketDetail: {
            name: 'Ticket detail',
            import: () => import('./frontend/scenes/ticket/ConversationsTicketScene'),
            projectBased: true,
            layout: 'app-container',
        },
        ConversationsSettings: {
            name: 'Conversations settings',
            import: () => import('./frontend/scenes/settings/ConversationsSettingsScene'),
            projectBased: true,
            layout: 'app-container',
        },
    },
    routes: {
        '/conversations/tickets': ['ConversationsTickets', 'conversationsTickets'],
        '/conversations/tickets/:ticketId': ['ConversationsTicketDetail', 'conversationsTicketDetail'],
        '/conversations/settings': ['ConversationsSettings', 'conversationsSettings'],
    },
    redirects: {
        '/conversations': '/conversations/tickets',
    },
    urls: {
        conversationsDashboard: (): string => '/conversations',
        conversationsTickets: (): string => '/conversations/tickets',
        conversationsTicketDetail: (ticketId: string | number): string => `/conversations/tickets/${ticketId}`,
        conversationsSettings: (): string => '/conversations/settings',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Conversations',
            intents: [ProductKey.CONVERSATIONS],
            category: 'Unreleased',
            href: urls.conversationsTickets(),
            type: 'conversations',
            flag: FEATURE_FLAGS.PRODUCT_CONVERSATIONS,
            tags: ['alpha'],
            iconType: 'chat',
            iconColor: ['var(--color-product-conversations-light)'] as FileSystemIconColor,
            sceneKey: 'ConversationsTickets',
        },
    ],
    treeItemsMetadata: [
        {
            path: 'Conversations',
            category: 'Unreleased',
            iconType: 'chat' as FileSystemIconType,
            iconColor: ['var(--color-product-conversations-light)'] as FileSystemIconColor,
            href: urls.conversationsTickets(),
            sceneKey: 'ConversationsTickets',
            flag: FEATURE_FLAGS.PRODUCT_CONVERSATIONS,
            tags: ['alpha'],
        },
    ],
}
