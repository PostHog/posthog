import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Conversations',
    scenes: {
        ConversationsDashboard: {
            name: 'Conversations overview',
            import: () => import('./frontend/scenes/dashboard/ConversationsDashboardScene'),
            projectBased: true,
        },
        ConversationsTickets: {
            name: 'Ticket list',
            import: () => import('./frontend/scenes/tickets/ConversationsTicketsScene'),
            projectBased: true,
        },
        ConversationsTicketDetail: {
            name: 'Ticket detail',
            import: () => import('./frontend/scenes/ticket/ConversationsTicketScene'),
            projectBased: true,
        },
        ConversationsAnalytics: {
            name: 'Resolution analytics',
            import: () => import('./frontend/scenes/analytics/ConversationsAnalyticsScene'),
            projectBased: true,
        },
        ConversationsContent: {
            name: 'Knowledge content',
            import: () => import('./frontend/scenes/content/ConversationsContentScene'),
            projectBased: true,
        },
        ConversationsGuidance: {
            name: 'Guidance + guardrails',
            import: () => import('./frontend/scenes/guidance/ConversationsGuidanceScene'),
            projectBased: true,
        },
        ConversationsPlayground: {
            name: 'Playground',
            import: () => import('./frontend/scenes/playground/ConversationsPlaygroundScene'),
            projectBased: true,
        },
        ConversationsSettings: {
            name: 'Conversations settings',
            import: () => import('./frontend/scenes/settings/ConversationsSettingsScene'),
            projectBased: true,
        },
    },
    routes: {
        '/conversations': ['ConversationsDashboard', 'conversationsDashboard'],
        '/conversations/tickets': ['ConversationsTickets', 'conversationsTickets'],
        '/conversations/tickets/:ticketId': ['ConversationsTicketDetail', 'conversationsTicketDetail'],
        '/conversations/analytics': ['ConversationsAnalytics', 'conversationsAnalytics'],
        '/conversations/content': ['ConversationsContent', 'conversationsContent'],
        '/conversations/guidance': ['ConversationsGuidance', 'conversationsGuidance'],
        '/conversations/playground': ['ConversationsPlayground', 'conversationsPlayground'],
        '/conversations/settings': ['ConversationsSettings', 'conversationsSettings'],
    },
    redirects: {},
    urls: {
        conversationsDashboard: (): string => '/conversations',
        conversationsTickets: (): string => '/conversations/tickets',
        conversationsTicketDetail: (ticketId: string | number): string => `/conversations/tickets/${ticketId}`,
        conversationsAnalytics: (): string => '/conversations/analytics',
        conversationsContent: (): string => '/conversations/content',
        conversationsGuidance: (): string => '/conversations/guidance',
        conversationsPlayground: (): string => '/conversations/playground',
        conversationsSettings: (): string => '/conversations/settings',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
    treeItemsMetadata: [],
}
