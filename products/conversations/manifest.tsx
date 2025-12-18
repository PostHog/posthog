import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Conversations',
    scenes: {
        ConversationsDashboard: {
            name: 'Conversations overview',
            import: () => import('./frontend/scenes/dashboard/ConversationsDashboardScene'),
            projectBased: true,
            iconType: 'chat',
            layout: 'app-container',
        },
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
        ConversationsContent: {
            name: 'Knowledge content',
            import: () => import('./frontend/scenes/content/ConversationsContentScene'),
            projectBased: true,
            layout: 'app-container',
        },
        ConversationsContentItem: {
            name: 'Content item',
            import: () => import('./frontend/scenes/content/ConversationsContentItemScene'),
            projectBased: true,
            layout: 'app-container',
        },
        ConversationsGuidance: {
            name: 'Guidance + guardrails',
            import: () => import('./frontend/scenes/guidance/ConversationsGuidanceScene'),
            projectBased: true,
            layout: 'app-container',
        },
        ConversationsGuidanceItem: {
            name: 'Guidance item',
            import: () => import('./frontend/scenes/guidance/ConversationsGuidanceItemScene'),
            projectBased: true,
            layout: 'app-container',
        },
        ConversationsPlayground: {
            name: 'Playground',
            import: () => import('./frontend/scenes/playground/ConversationsPlaygroundScene'),
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
        '/conversations/content': ['ConversationsContent', 'conversationsContent'],
        '/conversations/content/:contentId': ['ConversationsContentItem', 'conversationsContentItem'],
        '/conversations/guidance': ['ConversationsGuidance', 'conversationsGuidance'],
        '/conversations/guidance/:guidanceId': ['ConversationsGuidanceItem', 'conversationsGuidanceItem'],
        '/conversations/playground': ['ConversationsPlayground', 'conversationsPlayground'],
        '/conversations/settings': ['ConversationsSettings', 'conversationsSettings'],
    },
    redirects: {
        '/conversations': '/conversations/tickets',
    },
    urls: {
        conversationsDashboard: (): string => '/conversations',
        conversationsTickets: (): string => '/conversations/tickets',
        conversationsTicketDetail: (ticketId: string | number): string => `/conversations/tickets/${ticketId}`,
        conversationsContent: (): string => '/conversations/content',
        conversationsContentItem: (contentId: string | number): string => `/conversations/content/${contentId}`,
        conversationsGuidance: (): string => '/conversations/guidance',
        conversationsGuidanceItem: (guidanceId: string | number): string => `/conversations/guidance/${guidanceId}`,
        conversationsPlayground: (): string => '/conversations/playground',
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
            type: 'chat',
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
