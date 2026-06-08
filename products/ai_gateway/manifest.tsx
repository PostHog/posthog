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
            iconType: 'ai_gateway',
        },
        AIGatewayDetail: {
            import: () => import('./frontend/AIGatewayDetailScene'),
            projectBased: true,
            name: 'AI gateway',
            layout: 'app-container',
            iconType: 'ai_gateway',
        },
    },
    routes: {
        '/ai-gateway': ['AIGateway', 'aiGateway'],
        '/ai-gateway/:slug': ['AIGatewayDetail', 'aiGateway'],
    },
    redirects: {},
    urls: {
        aiGateway: (): string => '/ai-gateway',
        aiGatewayDetail: (slug: string): string => `/ai-gateway/${encodeURIComponent(slug)}`,
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
            iconColor: ['var(--color-product-llm-analytics-light)'] as FileSystemIconColor,
            href: urls.aiGateway(),
            flag: FEATURE_FLAGS.AI_GATEWAY,
            tags: ['alpha'],
            sceneKey: 'AIGateway',
        },
    ],
}
