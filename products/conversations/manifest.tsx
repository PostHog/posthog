import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'

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
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Support',
            intents: [ProductKey.CONVERSATIONS],
            category: 'Unreleased',
            href: urls.supportTickets(),
            type: 'conversations',
            flag: FEATURE_FLAGS.PRODUCT_SUPPORT,
            tags: ['alpha'],
            iconType: 'conversations',
            iconColor: ['var(--color-product-support-light)'] as FileSystemIconColor,
            sceneKey: 'SupportTickets',
        },
    ],
    treeItemsMetadata: [
        {
            path: 'Support',
            category: 'Unreleased',
            iconType: 'conversations' as FileSystemIconType,
            iconColor: ['var(--color-product-support-light)'] as FileSystemIconColor,
            href: urls.supportTickets(),
            sceneKey: 'SupportTickets',
            flag: FEATURE_FLAGS.PRODUCT_SUPPORT,
            tags: ['alpha'],
        },
    ],
}
