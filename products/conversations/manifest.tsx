import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Conversations',
    scenes: {
        SupportTickets: {
            name: 'Ticket list',
            import: () => import('./frontend/scenes/tickets/SupportTicketsScene'),
            projectBased: true,
            layout: 'app-container',
        },
        SupportTicketDetail: {
            name: 'Ticket detail',
            import: () => import('./frontend/scenes/ticket/SupportTicketScene'),
            projectBased: true,
            layout: 'app-container',
        },
        SupportTrends: {
            name: 'Ticket trends',
            import: () => import('./frontend/scenes/trends/SupportTrendsScene'),
            projectBased: true,
            layout: 'app-container',
        },
        SupportSettings: {
            name: 'Support settings',
            import: () => import('./frontend/scenes/settings/SupportSettingsScene'),
            projectBased: true,
            layout: 'app-container',
        },
    },
    routes: {
        '/support/tickets': ['SupportTickets', 'supportTickets'],
        '/support/tickets/:ticketId': ['SupportTicketDetail', 'supportTicketDetail'],
        '/support/trends': ['SupportTrends', 'supportTrends'],
        '/support/settings': ['SupportSettings', 'supportSettings'],
    },
    redirects: {
        '/support': '/support/tickets',
    },
    urls: {
        supportDashboard: (): string => '/support',
        supportTickets: (): string => '/support/tickets',
        supportTicketDetail: (ticketId: string | number): string => `/support/tickets/${ticketId}`,
        supportTrends: (): string => '/support/trends',
        supportSettings: (): string => '/support/settings',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Support',
            intents: [ProductKey.CONVERSATIONS],
            category: ProductItemCategory.BEHAVIOR,
            href: urls.supportTickets(),
            type: 'conversations',
            iconType: 'conversations',
            iconColor: ['var(--color-product-support-light)'] as FileSystemIconColor,
            sceneKey: 'SupportTickets',
        },
    ],
    treeItemsMetadata: [],
}
