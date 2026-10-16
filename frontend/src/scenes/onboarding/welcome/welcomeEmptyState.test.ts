import type { ProductEmptyStateConfig, SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { Scene, type SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { pickWelcomeEmptyState } from './welcomeEmptyState'

function sceneWith(emptyState: Partial<SceneProductEmptyState> & { productKey: ProductKey }): SceneExport {
    const { productKey, ...rest } = emptyState
    return {
        component: () => null,
        emptyState: {
            config: { productKey } as ProductEmptyStateConfig,
            statusLogic: {} as SceneProductEmptyState['statusLogic'],
            ...rest,
        },
    }
}

describe('pickWelcomeEmptyState', () => {
    test.each([
        {
            name: "the scene's own product",
            sceneExport: sceneWith({ productKey: ProductKey.SESSION_REPLAY }),
            expected: true,
        },
        {
            name: 'an empty state for another product',
            sceneExport: sceneWith({ productKey: ProductKey.ERROR_TRACKING }),
            expected: false,
        },
        {
            name: 'an empty state scoped to another scene',
            sceneExport: sceneWith({ productKey: ProductKey.SESSION_REPLAY, scenes: [Scene.WebAnalyticsWebVitals] }),
            expected: false,
        },
        {
            name: 'a scene with no empty state',
            sceneExport: { component: () => null },
            expected: false,
        },
    ])('$name', ({ sceneExport, expected }) => {
        const picked = pickWelcomeEmptyState(sceneExport, ProductKey.SESSION_REPLAY, Scene.Replay, {})
        expect(picked !== null).toBe(expected)
    })
})
