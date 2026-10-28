import { IconTarget } from '@posthog/icons'

import { urls } from 'scenes/urls'

import { ProductItemCategory } from '../../frontend/src/queries/schema/schema-general'
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Bets',
    railPane: {
        key: 'product:portfolio',
        label: 'Bets',
        icon: <IconTarget />,
        path: '/bets',
        href: () => urls.bets(),
        flag: 'bets',
        sidebarScene: 'BetsSidebar',
    },
    scenes: {
        BetsSidebar: {
            name: 'Bets',
            projectBased: true,
            import: () => import('./frontend/BetsSidebar'),
            iconType: 'experiment',
        },
        BetsOverview: {
            name: 'Overview',
            projectBased: true,
            import: () => import('./frontend/scenes/BetsOverviewScene'),
            iconType: 'experiment',
        },
        BetsAll: {
            name: 'All bets',
            projectBased: true,
            import: () => import('./frontend/scenes/AllBetsScene'),
            iconType: 'experiment',
        },
        BetDetail: {
            name: 'Bet',
            projectBased: true,
            import: () => import('./frontend/scenes/BetDetailScene'),
            iconType: 'experiment',
        },
        BetEdit: {
            name: 'Define a bet',
            projectBased: true,
            import: () => import('./frontend/scenes/BetEditScene'),
            iconType: 'experiment',
        },
        BetsSettings: {
            name: 'Bets settings',
            projectBased: true,
            import: () => import('./frontend/scenes/BetsSettingsScene'),
            iconType: 'experiment',
        },
    },
    routes: {
        '/bets': ['BetsOverview', 'bets'],
        '/bets/all': ['BetsAll', 'betsAll'],
        '/bets/new': ['BetEdit', 'betsNew'],
        '/bets/settings': ['BetsSettings', 'betsSettings'],
        '/bets/:id/edit': ['BetEdit', 'betEdit'],
        '/bets/:id': ['BetDetail', 'bet'],
    },
    redirects: {
        '/portfolio': '/bets',
        '/portfolio/bets': '/bets/all',
        '/portfolio/new': '/bets/new',
        '/portfolio/settings': '/bets/settings',
        '/portfolio/setup': '/bets/settings',
        '/portfolio/map': '/bets',
        '/portfolio/bets/:id': ({ id }) => '/bets/' + id,
        '/portfolio/theses/:id': '/bets',
        '/portfolio/research/:id': '/bets',
        '/bets/positions/:id': ({ id }) => '/bets/' + id,
        '/bets/setup': '/bets/settings',
    },
    urls: {
        bets: (): string => '/bets',
        betsAll: (): string => '/bets/all',
        betsNew: (): string => '/bets/new',
        betsSettings: (): string => '/bets/settings',
        bet: (id: string): string => `/bets/${id}`,
        betEdit: (id: string): string => `/bets/${id}/edit`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Bets',
            category: ProductItemCategory.UNRELEASED,
            href: urls.bets(),
            searchKeywords: ['bets', 'portfolio', 'north star'],
            iconType: 'experiment',
            flag: 'bets',
            tags: ['alpha'],
            sceneKey: 'BetsOverview',
            intents: [],
        },
    ],
}
