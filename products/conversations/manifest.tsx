import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Support',
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
        '/support/settings': ['SupportSettings', 'supportSettings'],
    },
    redirects: {
        '/support': '/support/tickets',
    },
    urls: {
        supportDashboard: (): string => '/support',
        supportTickets: (): string => '/support/tickets',
        supportTicketDetail: (ticketId: string | number): string => `/support/tickets/${ticketId}`,
        supportSettings: (): string => '/support/settings',
    },
    fileSystemTypes: {
        ticket: {
            name: 'Ticket',
            iconType: 'conversations',
            iconColor: [
                'var(--color-product-support-light)',
                'var(--color-product-support-dark)',
            ] as FileSystemIconColor,
            href: (ref: string) => urls.supportTicketDetail(ref),
            filterKey: 'ticket',
        },
    },
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
