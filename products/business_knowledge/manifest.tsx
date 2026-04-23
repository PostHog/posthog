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
                'Upload text your AI support agent can cite when answering customer tickets. URLs and files come in later stages.',
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
