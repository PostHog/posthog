import type { ProductEmptyStateConfig, SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { Scene } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { pickWelcomeEmptyState } from './welcomeEmptyState'

function emptyStateWith(
    emptyState: Partial<SceneProductEmptyState> & { productKey: ProductKey }
): SceneProductEmptyState {
    const { productKey, ...rest } = emptyState
    return {
        config: { productKey } as ProductEmptyStateConfig,
        statusLogic: {} as SceneProductEmptyState['statusLogic'],
        ...rest,
    }
}

describe('pickWelcomeEmptyState', () => {
    test.each([
        {
            name: "the scene's own product",
            emptyState: emptyStateWith({ productKey: ProductKey.SESSION_REPLAY }),
            expected: true,
        },
        {
            name: 'an empty state for another product',
            emptyState: emptyStateWith({ productKey: ProductKey.ERROR_TRACKING }),
            expected: false,
        },
        {
            name: 'an empty state scoped to another scene',
            emptyState: emptyStateWith({ productKey: ProductKey.SESSION_REPLAY, scenes: [Scene.Heatmaps] }),
            expected: false,
        },
    ])('$name', ({ emptyState, expected }) => {
        const picked = pickWelcomeEmptyState(emptyState, ProductKey.SESSION_REPLAY, Scene.Replay, {})
        expect(picked !== null).toBe(expected)
    })
})
