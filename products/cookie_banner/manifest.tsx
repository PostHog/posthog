import { FEATURE_FLAGS } from 'lib/constants'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Cookie banner',
    scenes: {
        CookieBanner: {
            name: 'Cookie banner',
            import: () => import('./frontend/CookieBannerScene'),
            projectBased: true,
            description: 'Show a compliant cookie consent banner on your website, no extra vendor needed.',
            iconType: 'default_icon_type',
        },
    },
    routes: {
        '/cookie-banner': ['CookieBanner', 'cookieBanner'],
    },
    urls: {
        cookieBanner: (): string => '/cookie-banner',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Cookie banner',
            intents: [ProductKey.COOKIE_BANNER],
            category: ProductItemCategory.UNRELEASED,
            href: '/cookie-banner',
            iconType: 'default_icon_type',
            flag: FEATURE_FLAGS.COOKIE_BANNER,
            tags: ['alpha'],
            sceneKey: 'CookieBanner',
        },
    ],
}
