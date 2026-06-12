import { FileSystemIconType } from '@posthog/query-frontend/schema/schema-general'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Core Events',
    treeItemsMetadata: [
        {
            path: 'Core events',
            category: 'Schema',
            iconType: 'event_definition' as FileSystemIconType,
            href: urls.coreEvents(),
            flag: FEATURE_FLAGS.NEW_TEAM_CORE_EVENTS,
        },
    ],
}
