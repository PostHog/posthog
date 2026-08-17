import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Support',
    scenes: {
        SupportTickets: {
            name: 'Ticket list',
            description:
                'Collect support tickets from an in-app widget, email, or Slack into one inbox, with the product context behind every ticket',
            iconType: 'conversations',
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
        SupportSettings: {
            name: 'Support settings',
            import: () => import('./frontend/scenes/settings/SupportSettingsScene'),
            projectBased: true,
            layout: 'app-container',
        },
        // The user's own tickets with PostHog support — unrelated to the Support product's
        // agent inbox above, which shows tickets from *their* customers
        MyTickets: {
            name: 'Your tickets',
            import: () => import('./frontend/scenes/myTickets/MyTicketsScene'),
            projectBased: true,
            layout: 'app-container',
        },
    },
    routes: {
        '/support/tickets': ['SupportTickets', 'supportTickets'],
        '/support/tickets/:ticketId': ['SupportTicketDetail', 'supportTicketDetail'],
        '/support/settings': ['SupportSettings', 'supportSettings'],
        '/my-tickets': ['MyTickets', 'myTickets'],
    },
    redirects: {
        '/support': '/support/tickets',
    },
    urls: {
        supportDashboard: (): string => '/support',
        supportTickets: (): string => '/support/tickets',
        supportTicketDetail: (ticketId: string | number): string => `/support/tickets/${ticketId}`,
        supportSettings: (): string => '/support/settings',
        myTickets: (ticketId?: string): string =>
            ticketId ? `/my-tickets?ticket=${encodeURIComponent(ticketId)}` : '/my-tickets',
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
            iconColor: [
                'var(--color-product-support-light)',
                'var(--color-product-support-dark)',
            ] as FileSystemIconColor,
            sceneKey: 'SupportTickets',
        },
    ],
    treeItemsMetadata: [],
}
