import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'CSM HUD',
    scenes: {
        CSMHud: {
            import: () => import('./frontend/scenes/CSMHudScene'),
            projectBased: true,
            name: 'CSM HUD',
            description: 'Customer Success Manager portfolio dashboard.',
            layout: 'app-container',
        },
        CSMHudCustomer: {
            import: () => import('./frontend/scenes/CSMHudCustomerScene'),
            projectBased: true,
            name: 'CSM HUD customer',
            layout: 'app-container',
        },
    },
    routes: {
        '/csm-hud': ['CSMHud', 'csmHud'],
        '/csm-hud/fleet': ['CSMHud', 'csmHudFleet'],
        '/csm-hud/renewals': ['CSMHud', 'csmHudRenewals'],
        '/csm-hud/engagement': ['CSMHud', 'csmHudEngagement'],
        '/csm-hud/conversations': ['CSMHud', 'csmHudConversations'],
        '/csm-hud/expansion': ['CSMHud', 'csmHudExpansion'],
        '/csm-hud/customer/:externalId': ['CSMHudCustomer', 'csmHudCustomer'],
    },
    redirects: {
        '/csm-hud': '/csm-hud/fleet',
    },
    urls: {
        csmHud: (): string => '/csm-hud/fleet',
        csmHudFleet: (): string => '/csm-hud/fleet',
        csmHudRenewals: (): string => '/csm-hud/renewals',
        csmHudEngagement: (): string => '/csm-hud/engagement',
        csmHudConversations: (): string => '/csm-hud/conversations',
        csmHudExpansion: (): string => '/csm-hud/expansion',
        csmHudCustomer: (externalId: string): string => `/csm-hud/customer/${encodeURIComponent(externalId)}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
