import {
    type ProductEmptyStateGateRender,
    productEmptyStateGateRender,
} from 'lib/components/ProductEmptyState/gateRender'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { FEATURE_FLAGS } from 'lib/constants'

import { ProductKey } from '~/queries/schema/schema-general'

import { type PendingProductPushWelcome, shouldShowProductPushWelcome } from './navPanelProductPushWelcomeVisibility'

const PENDING: PendingProductPushWelcome = {
    campaignId: 'campaign-1',
    productKey: ProductKey.PRODUCT_ANALYTICS,
    label: 'Product analytics',
    text: 'Insights, funnels, trends, and retention.',
}

const emptyState = (extra: Partial<SceneProductEmptyState> = {}, skippable?: boolean): SceneProductEmptyState =>
    ({ config: { productKey: ProductKey.PRODUCT_ANALYTICS, skippable }, ...extra }) as SceneProductEmptyState

type GateArgs = Parameters<typeof productEmptyStateGateRender>[0]

const gateRender = (overrides: Partial<GateArgs> = {}): ProductEmptyStateGateRender =>
    productEmptyStateGateRender({
        emptyState: emptyState(),
        activeSceneId: 'ProductAnalytics',
        params: {},
        featureFlags: {},
        receivedFeatureFlags: true,
        forcedMode: null,
        status: 'needs-setup',
        skipped: false,
        ...overrides,
    })

describe('shouldShowProductPushWelcome', () => {
    // The modal stands in for a setup screen the user will not see, so the two must never both
    // claim the scene, and the one case the modal exists for (a gated scene that has data) must
    // still reach it.
    it.each<[string, Partial<Parameters<typeof shouldShowProductPushWelcome>[0]>, boolean]>([
        ['no click to follow up on', { pending: null }, false],
        [
            'still on the scene the click came from',
            { activeSceneProductKey: ProductKey.SESSION_REPLAY, pushedProductGate: null },
            false,
        ],
        [
            'on a scene that belongs to one product and gates on the pushed one',
            {
                pending: { ...PENDING, productKey: ProductKey.DASHBOARDS },
                activeSceneProductKey: ProductKey.PRODUCT_ANALYTICS,
                pushedProductGate: 'scene',
            },
            true,
        ],
        ['the scene gates on setup and is still resolving it', { pushedProductGate: 'loading' }, false],
        ['the scene is showing the setup screen', { pushedProductGate: 'setup' }, false],
        ['the gate handed the scene through', { pushedProductGate: 'scene' }, true],
        ['the scene has no setup screen for the pushed product', { pushedProductGate: null }, true],
    ])('%s', (_description, overrides, expected) => {
        expect(
            shouldShowProductPushWelcome({
                pending: PENDING,
                activeSceneProductKey: ProductKey.PRODUCT_ANALYTICS,
                pushedProductGate: 'setup',
                ...overrides,
            })
        ).toBe(expected)
    })

    // What the gate declares is not what it renders: it stands down for a flag or a scene scope,
    // and `?empty_state=1` puts the setup screen on a product that has data. Reading the setup
    // status alone gets both of those backwards.
    it.each<[string, Partial<GateArgs>, boolean]>([
        ['the product needs setup, so the gate is showing the screen', {}, false],
        ['the product is waiting for its first events', { status: 'waiting-for-data' }, false],
        ['detection is still running', { status: 'loading' }, false],
        ['the product already has data', { status: 'has-data' }, true],
        ['detection failed and the gate failed open', { status: 'unknown' }, true],
        ['the user skipped the setup screen', { skipped: true }, true],
        [
            'the user skipped a product that cannot be skipped',
            { emptyState: emptyState({}, false), skipped: true },
            false,
        ],
        [
            'the gate is off because its own feature flag is disabled',
            { emptyState: emptyState({ featureFlag: FEATURE_FLAGS.SCENE_MENU_BAR }) },
            true,
        ],
        [
            "the gate's own feature flag has not arrived yet",
            {
                emptyState: emptyState({ featureFlag: FEATURE_FLAGS.SCENE_MENU_BAR }),
                receivedFeatureFlags: false,
            },
            false,
        ],
        [
            'the gate is scoped to scenes this one is not among',
            { emptyState: emptyState({ scenes: ['SomeOtherScene'] }) },
            true,
        ],
        [
            'the gate is bypassed by its bypass flag',
            {
                emptyState: emptyState({ bypassFeatureFlag: FEATURE_FLAGS.SCENE_MENU_BAR }),
                featureFlags: { [FEATURE_FLAGS.SCENE_MENU_BAR]: true },
            },
            true,
        ],
        [
            'the bypass flag has not arrived yet',
            {
                emptyState: emptyState({ bypassFeatureFlag: FEATURE_FLAGS.SCENE_MENU_BAR }),
                receivedFeatureFlags: false,
            },
            false,
        ],
        [
            'the setup screen is forced onto a product that has data',
            { status: 'has-data', forcedMode: 'needs-setup' },
            false,
        ],
    ])('%s', (_description, overrides, expected) => {
        expect(
            shouldShowProductPushWelcome({
                pending: PENDING,
                activeSceneProductKey: ProductKey.PRODUCT_ANALYTICS,
                pushedProductGate: gateRender(overrides),
            })
        ).toBe(expected)
    })
})
