import type { StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import type { Mocks } from '~/mocks/utils'

import type { ProductEmptyState } from './ProductEmptyState'
import type { ProductEmptyStateConfig, ProductEmptyStateMode, SceneProductEmptyState } from './types'

export type ProductEmptyStateStory = StoryObj<typeof ProductEmptyState>

export interface ProductEmptyStateStoryOptions {
    /** Per-story overrides on top of the product's real config, e.g. `{ wizard: undefined }` for the self-hosted rendering */
    config?: Partial<ProductEmptyStateConfig>
    /** Extra msw handlers, merged over the defaults (same path wins), e.g. to drive the product's status indicator into a specific state */
    mocks?: Mocks
}

/**
 * Builds a story (and therefore a visual-regression snapshot) for a product's real
 * empty-state config - the exact object its scene gate renders. A product adopting
 * the platform adds one export per mode:
 *
 *     export const MyProductNeedsSetup = productEmptyStateStory(myProductEmptyState, 'needs-setup')
 *
 * Detection logics and status indicators issue requests on mount; the default mocks
 * answer the common ones (queries with empty results, product intents with 200) so a
 * bare call renders cleanly without msw warnings. Pass `mocks` to override.
 */
export function productEmptyStateStory(
    emptyState: SceneProductEmptyState,
    mode: ProductEmptyStateMode,
    { config, mocks }: ProductEmptyStateStoryOptions = {}
): ProductEmptyStateStory {
    return {
        // Empty states show a persistent "listening for data" spinner (and animated preview)
        // by design, so the snapshot runner must not wait for loaders to disappear here.
        parameters: { testOptions: { waitForLoadersToDisappear: false } },
        args: { config: { ...emptyState.config, ...config }, mode },
        decorators: [
            mswDecorator({
                ...mocks,
                post: {
                    // nosemgrep: no-environments-api-urls-frontend -- api.query is env-scoped, so the msw mock must match /api/environments to intercept it
                    '/api/environments/:team_id/query/:kind': [200, { results: [] }],
                    ...mocks?.post,
                },
                patch: {
                    // nosemgrep: no-environments-api-urls-frontend -- add_product_intent is env-scoped, so the msw mock must match /api/environments to intercept it
                    '/api/environments/:team_id/add_product_intent': [200, {}],
                    ...mocks?.patch,
                },
            }),
        ],
    }
}
