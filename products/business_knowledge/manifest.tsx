/**
 * Product manifest for business_knowledge.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'BusinessKnowledge',
    scenes: {
        BusinessKnowledge: {
            name: 'Business knowledge',
            import: () => import('./frontend/scenes/BusinessKnowledgeScene'),
            projectBased: true,
            activityScope: 'KnowledgeSource',
            description:
                'Upload text, public URLs, or files your AI support agent can cite when answering customer tickets.',
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
    treeItemsProducts: [],
}
