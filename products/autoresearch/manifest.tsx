import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Autoresearch',
    scenes: {
        Autoresearch: {
            name: 'Autoresearch',
            import: () => import('./frontend/AutoresearchScene'),
            projectBased: true,
            description: 'Automatically find the best model to predict user behavior and score your users daily.',
            iconType: 'experiment',
        },
        AutoresearchPipeline: {
            name: 'Autoresearch pipeline',
            import: () => import('./frontend/AutoresearchPipelineScene'),
            projectBased: true,
        },
    },
    routes: {
        '/autoresearch': ['Autoresearch', 'autoresearch'],
        '/autoresearch/:id': ['AutoresearchPipeline', 'autoresearchPipeline'],
    },
    urls: {
        autoresearch: (): string => '/autoresearch',
        autoresearchPipeline: (id: string): string => `/autoresearch/${id}`,
    },
    treeItemsProducts: [
        {
            path: 'Autoresearch',
            intents: [ProductKey.AUTORESEARCH],
            category: ProductItemCategory.UNRELEASED,
            type: 'autoresearch',
            href: urls.autoresearch(),
            flag: FEATURE_FLAGS.AUTORESEARCH,
            iconType: 'experiment',
            tags: ['alpha'],
            sceneKey: 'Autoresearch',
        },
    ],
}
