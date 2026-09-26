/**
 * Product manifest for business_knowledge.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'BusinessKnowledge',
    scenes: {
        BusinessKnowledge: {
            name: 'Business knowledge',
            import: () => import('./frontend/scenes/BusinessKnowledgeScene'),
            projectBased: true,
            activityScope: 'KnowledgeSource',
            iconType: 'conversations',
            description:
                'Upload text, public URLs, or files so PostHog AI can understand your business context, vision, and policies.',
        },
        BusinessKnowledgeSettings: {
            name: 'Business knowledge settings',
            import: () => import('./frontend/scenes/BusinessKnowledgeSettingsScene'),
            projectBased: true,
            iconType: 'conversations',
        },
        BusinessKnowledgeSource: {
            name: 'Knowledge source',
            import: () => import('./frontend/scenes/KnowledgeSourceScene'),
            projectBased: true,
            activityScope: 'KnowledgeSource',
            iconType: 'conversations',
        },
    },
    routes: {
        '/business-knowledge': ['BusinessKnowledge', 'businessKnowledge'],
        // Static sibling must stay above :id so kea-router does not treat "settings" as an id.
        '/business-knowledge/settings': ['BusinessKnowledgeSettings', 'businessKnowledgeSettings'],
        '/business-knowledge/:id': ['BusinessKnowledgeSource', 'businessKnowledgeSource'],
    },
    redirects: {},
    urls: {
        businessKnowledge: (): string => '/business-knowledge',
        businessKnowledgeSettings: (): string => '/business-knowledge/settings',
        businessKnowledgeSource: (id: string): string => `/business-knowledge/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Business knowledge',
            intents: [ProductKey.CONVERSATIONS],
            category: ProductItemCategory.DATA,
            href: urls.businessKnowledge(),
            tags: ['alpha'],
            iconType: 'business_knowledge',
            iconColor: [
                'var(--color-product-business-knowledge-light)',
                'var(--color-product-business-knowledge-dark)',
            ],
            flag: FEATURE_FLAGS.PRODUCT_BUSINESS_KNOWLEDGE,
            sceneKey: 'BusinessKnowledge',
        },
    ],
}
