import type { ProductSetupStatus, SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { type PendingProductPushWelcome, shouldShowProductPushWelcome } from './navPanelProductPushWelcomeVisibility'

const PENDING: PendingProductPushWelcome = {
    campaignId: 'campaign-1',
    productKey: ProductKey.PRODUCT_ANALYTICS,
    label: 'Product analytics',
    text: 'Insights, funnels, trends, and retention.',
}

const gateFor = (productKey: ProductKey, skippable?: boolean): SceneProductEmptyState =>
    ({ config: { productKey, skippable } }) as SceneProductEmptyState

describe('shouldShowProductPushWelcome', () => {
    // The modal stands in for a setup screen the user will not see, so the two must never both
    // claim the scene, and the one case the modal exists for (a gated scene that has data) must
    // still reach it.
    it.each<[string, Partial<Parameters<typeof shouldShowProductPushWelcome>[0]>, boolean]>([
        ['no click to follow up on', { pending: null }, false],
        [
            'still on the scene the click came from',
            { activeSceneProductKey: ProductKey.SESSION_REPLAY, sceneEmptyState: undefined },
            false,
        ],
        [
            'on a scene that belongs to one product and gates on the pushed one',
            {
                pending: { ...PENDING, productKey: ProductKey.DASHBOARDS },
                sceneEmptyState: gateFor(ProductKey.DASHBOARDS),
                status: 'has-data' as ProductSetupStatus,
            },
            true,
        ],
        ['the scene gates on setup and is still resolving it', { status: 'loading' }, false],
        ['the scene is showing the setup screen', { status: 'needs-setup' }, false],
        ['the scene is waiting for the first events', { status: 'waiting-for-data' }, false],
        ['the product already has data', { status: 'has-data' }, true],
        ['detection failed and the gate failed open', { status: 'unknown' }, true],
        ['the user skipped the setup screen', { status: 'needs-setup', skipped: true }, true],
        [
            'the user skipped a product that cannot be skipped',
            {
                status: 'needs-setup',
                skipped: true,
                sceneEmptyState: gateFor(ProductKey.PRODUCT_ANALYTICS, false),
            },
            false,
        ],
        ['the scene gates on another product', { sceneEmptyState: gateFor(ProductKey.SESSION_REPLAY) }, true],
        ['the scene has no setup screen at all', { sceneEmptyState: undefined }, true],
    ])('%s', (_description, overrides, expected) => {
        expect(
            shouldShowProductPushWelcome({
                pending: PENDING,
                activeSceneProductKey: ProductKey.PRODUCT_ANALYTICS,
                sceneEmptyState: gateFor(ProductKey.PRODUCT_ANALYTICS),
                status: 'loading' as ProductSetupStatus,
                skipped: false,
                ...overrides,
            })
        ).toBe(expected)
    })
})
