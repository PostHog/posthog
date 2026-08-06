/**
 * Product manifest for business_knowledge.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'BusinessKnowledge',
    scenes: {
        BusinessKnowledge: {
            name: 'Business knowledge',
            import: () => import('./frontend/scenes/BusinessKnowledgeScene'),
            projectBased: true,
            activityScope: 'KnowledgeSource',
            description:
                'Upload text, public URLs, or files so PostHog AI can understand your business context, vision, and policies.',
        },
    },
    routes: {
        '/business-knowledge': ['BusinessKnowledge', 'businessKnowledge'],
    },
    redirects: {},
    urls: {
        businessKnowledge: (): string => '/business-knowledge',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Business knowledge',
            intents: [ProductKey.CONVERSATIONS],
            category: ProductItemCategory.AI_ENGINEERING,
            href: urls.businessKnowledge(),
            tags: ['alpha'],
            iconType: 'conversations',
            iconColor: ['var(--color-product-support-light)'] as FileSystemIconColor,
            flag: FEATURE_FLAGS.PRODUCT_BUSINESS_KNOWLEDGE,
            sceneKey: 'BusinessKnowledge',
        },
    ],
}
