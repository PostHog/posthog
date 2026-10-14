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
            import: () => import('./frontend/scenes/sources/BusinessKnowledgeScene'),
            projectBased: true,
            activityScope: 'KnowledgeSource',
            iconType: 'business_knowledge',
            description:
                'Upload text, public URLs, or files so PostHog AI can understand your business context, vision, and policies.',
        },
        BusinessKnowledgePlayground: {
            name: 'Business knowledge playground',
            import: () =>
                import('products/business_knowledge/frontend/scenes/playground/BusinessKnowledgePlaygroundScene'),
            projectBased: true,
            iconType: 'business_knowledge',
        },
        BusinessKnowledgeSettings: {
            name: 'Business knowledge settings',
            import: () => import('./frontend/scenes/settings/BusinessKnowledgeSettingsScene'),
            projectBased: true,
            iconType: 'business_knowledge',
        },
        BusinessKnowledgeSource: {
            name: 'Knowledge source',
            import: () => import('./frontend/scenes/source/KnowledgeSourceScene'),
            projectBased: true,
            activityScope: 'KnowledgeSource',
            iconType: 'business_knowledge',
        },
    },
    routes: {
        '/business-knowledge': ['BusinessKnowledge', 'businessKnowledge'],
        // Static sibling must stay above :id so kea-router does not treat "settings" as an id.
        '/business-knowledge/settings': ['BusinessKnowledgeSettings', 'businessKnowledgeSettings'],
        // Static sibling must stay above :id so kea-router does not treat "playground" as an id.
        '/business-knowledge/playground': ['BusinessKnowledgePlayground', 'businessKnowledgePlayground'],
        '/business-knowledge/playground/:chatId': ['BusinessKnowledgePlayground', 'businessKnowledgePlayground'],
        '/business-knowledge/:id': ['BusinessKnowledgeSource', 'businessKnowledgeSource'],
    },
    redirects: {},
    urls: {
        businessKnowledge: (): string => '/business-knowledge',
        businessKnowledgeSettings: (): string => '/business-knowledge/settings',
        businessKnowledgePlayground: (chatId?: string): string =>
            chatId ? `/business-knowledge/playground/${chatId}` : '/business-knowledge/playground',
        businessKnowledgeSource: (id: string): string => `/business-knowledge/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Business knowledge',
            intents: [ProductKey.BUSINESS_KNOWLEDGE],
            category: ProductItemCategory.DATA,
            href: urls.businessKnowledge(),
            searchKeywords: ['knowledge base', 'company context'],
            searchTabs: [{ name: 'Playground', href: urls.businessKnowledgePlayground() }],
            tags: ['beta'],
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
