import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { FileSystemIconColor, ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'AI gateway',
    scenes: {
        AIGateway: {
            import: () => import('./frontend/AIGatewayScene'),
            projectBased: true,
            name: 'AI gateway',
            description: 'Every major LLM through one endpoint, billed at cost — usage tracked per project.',
            layout: 'app-container',
            iconType: 'ai_gateway',
        },
    },
    routes: {
        '/ai-gateway': ['AIGateway', 'aiGateway'],
    },
    redirects: {},
    urls: {
        aiGateway: (): string => '/ai-gateway',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'AI gateway',
            intents: [ProductKey.AI_GATEWAY],
            category: ProductItemCategory.AI_ENGINEERING,
            type: 'ai_gateway',
            iconType: 'ai_gateway' as FileSystemIconType,
            iconColor: [
                'var(--color-product-ai-gateway-light)',
                'var(--color-product-ai-gateway-dark)',
            ] as FileSystemIconColor,
            href: urls.aiGateway(),
            flag: FEATURE_FLAGS.AI_GATEWAY,
            tags: ['alpha'],
            sceneKey: 'AIGateway',
        },
    ],
}
