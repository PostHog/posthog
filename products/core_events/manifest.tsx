import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Core Events',
    treeItemsMetadata: [
        {
            path: 'Core events',
            category: 'Schema',
            iconType: 'core_event',
            iconColor: ['var(--color-product-core-events-light)', 'var(--color-product-core-events-dark)'],
            href: urls.coreEvents(),
            flag: FEATURE_FLAGS.NEW_TEAM_CORE_EVENTS,
        },
    ],
}
