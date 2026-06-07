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
            description: 'Manage the gateways your LLM credentials attribute their usage and spend to.',
            layout: 'app-container',
            iconType: 'llm_analytics',
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
            iconType: 'llm_analytics' as FileSystemIconType,
            iconColor: ['var(--color-product-llm-analytics-light)'] as FileSystemIconColor,
            href: urls.aiGateway(),
            flag: FEATURE_FLAGS.AI_GATEWAY,
            tags: ['alpha'],
            sceneKey: 'AIGateway',
        },
    ],
}
