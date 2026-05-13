/**
 * Product manifest for agentic_tests.
 *
 * Defines scenes, routes, URLs, and navigation for the Agentic tests product.
 */
import { combineUrl } from 'kea-router'

import { FileSystemIconType, ProductItemCategory } from '../../frontend/src/queries/schema/schema-general'
import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Agentic tests',
    scenes: {
        AgenticTests: {
            import: () => import('./frontend/scenes/AgenticTestsScene/AgenticTestsScene'),
            projectBased: true,
            name: 'Agentic tests',
            iconType: 'agentic_tests',
            description: 'LLM-driven browser checks, seeded by your session replays.',
        },
        AgenticTest: {
            import: () => import('./frontend/scenes/AgenticTestScene/AgenticTestScene'),
            projectBased: true,
            name: 'Agentic test',
            iconType: 'agentic_tests',
        },
        AgenticTestNew: {
            import: () => import('./frontend/scenes/AgenticTestScene/AgenticTestScene'),
            projectBased: true,
            name: 'New agentic test',
            iconType: 'agentic_tests',
        },
    },
    routes: {
        '/agentic_tests': ['AgenticTests', 'agenticTests'],
        '/agentic_tests/new': ['AgenticTestNew', 'agenticTestNew'],
        '/agentic_tests/:id': ['AgenticTest', 'agenticTest'],
    },
    redirects: {},
    urls: {
        agenticTests: (params: Record<string, string> = {}): string => combineUrl('/agentic_tests', params).url,
        agenticTestNew: (params: Record<string, string> = {}): string => combineUrl('/agentic_tests/new', params).url,
        agenticTest: (id: string): string => `/agentic_tests/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [
        {
            path: 'Agentic test',
            type: 'agentic_test',
            href: '/agentic_tests/new',
        },
    ],
    treeItemsProducts: [
        {
            path: 'Agentic tests',
            category: ProductItemCategory.BEHAVIOR,
            type: 'agentic_tests',
            iconType: 'agentic_tests' as FileSystemIconType,
            iconColor: [
                'var(--color-product-llm-analytics-light)',
                'var(--color-product-llm-analytics-dark)',
            ] as FileSystemIconColor,
            href: '/agentic_tests',
            sceneKey: 'AgenticTests',
        },
    ],
}
