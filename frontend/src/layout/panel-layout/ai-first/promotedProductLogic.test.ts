import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { localStorageOverrideKey, localStorageProductKey, promotedProductLogic } from './promotedProductLogic'

const PRODUCT_KEY = localStorageProductKey(MOCK_TEAM_ID)
const OVERRIDE_KEY = localStorageOverrideKey(MOCK_TEAM_ID)

jest.mock('posthog-js')
const mockedPosthog = posthog as jest.Mocked<typeof posthog>

describe('promotedProductLogic', () => {
    let logic: ReturnType<typeof promotedProductLogic.build>

    const setFlagVariant = (variant: string | boolean | undefined): void => {
        featureFlagLogic.actions.setFeatureFlags(
            variant ? [FEATURE_FLAGS.PROMOTED_PRODUCT] : [],
            variant ? { [FEATURE_FLAGS.PROMOTED_PRODUCT]: variant } : {}
        )
    }

    const mountLogic = (): void => {
        logic = promotedProductLogic()
        logic.mount()
    }

    beforeEach(() => {
        jest.clearAllMocks()
        window.localStorage.clear()
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => {
        if (logic) {
            logic.unmount()
        }
    })

    describe('variant gating', () => {
        it.each([
            ['control', false, false],
            ['control_b', false, false],
            ['intent', true, false],
            ['intent_plus', true, true],
        ])('variant=%s → shouldRenderEntry=%s shouldRenderCog=%s', async (variant, renderEntry, renderCog) => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            mountLogic()
            setFlagVariant(variant)

            await expectLogic(logic).toMatchValues({
                variant,
                shouldRenderEntry: renderEntry,
                shouldRenderCog: renderCog,
            })
        })

        it('hides entry when flag is missing', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            mountLogic()
            setFlagVariant(undefined)

            await expectLogic(logic).toMatchValues({
                variant: null,
                shouldRenderEntry: false,
            })
        })

        it('hides entry when no intent is available even for intent variant', async () => {
            mountLogic()
            setFlagVariant('intent')

            await expectLogic(logic).toMatchValues({
                shouldRenderEntry: false,
            })
        })
    })

    describe('effectiveTarget', () => {
        it('resolves from localStorage when set', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'web_analytics')
            mountLogic()
            setFlagVariant('intent')

            await expectLogic(logic).toMatchValues({
                effectiveTarget: { kind: 'product', value: 'web_analytics' },
            })
        })

        it('intent_plus prefers override over onboarding intent', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            window.localStorage.setItem(OVERRIDE_KEY, JSON.stringify({ kind: 'url', value: '/my-page' }))
            mountLogic()
            setFlagVariant('intent_plus')

            await expectLogic(logic).toMatchValues({
                effectiveTarget: { kind: 'url', value: '/my-page' },
            })
        })

        it('intent variant ignores the override (cog is intent_plus only)', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            window.localStorage.setItem(OVERRIDE_KEY, JSON.stringify({ kind: 'url', value: '/my-page' }))
            mountLogic()
            setFlagVariant('intent')

            await expectLogic(logic).toMatchValues({
                effectiveTarget: { kind: 'product', value: 'session_replay' },
            })
        })

        it('rejects an unknown product key from onboarding intent', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'fictional_product')
            mountLogic()
            setFlagVariant('intent')

            await expectLogic(logic).toMatchValues({
                effectiveTarget: null,
                shouldRenderEntry: false,
            })
        })
    })

    describe('tracking', () => {
        it('captures click with target details', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            mountLogic()
            setFlagVariant('intent')

            logic.actions.trackPromotedProductClick()

            expect(mockedPosthog.capture).toHaveBeenCalledWith(
                'promoted product clicked',
                expect.objectContaining({
                    variant: 'intent',
                    kind: 'product',
                    product_key: 'session_replay',
                })
            )
        })

        it('does not capture click when there is no target', async () => {
            mountLogic()
            setFlagVariant('intent')

            logic.actions.trackPromotedProductClick()

            expect(mockedPosthog.capture).not.toHaveBeenCalledWith('promoted product clicked', expect.anything())
        })

        it('captures config opened with current target context', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            mountLogic()
            setFlagVariant('intent_plus')

            logic.actions.showConfigureModal()

            expect(mockedPosthog.capture).toHaveBeenCalledWith(
                'promoted product config opened',
                expect.objectContaining({
                    variant: 'intent_plus',
                    current_target_kind: 'product',
                    current_target_value: 'session_replay',
                })
            )
        })

        it('persists override to localStorage and captures config changed', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            mountLogic()
            setFlagVariant('intent_plus')

            logic.actions.setOverride({ kind: 'url', value: '/my-page' })

            expect(window.localStorage.getItem(OVERRIDE_KEY)).toBe(JSON.stringify({ kind: 'url', value: '/my-page' }))
            expect(mockedPosthog.capture).toHaveBeenCalledWith(
                'promoted product config changed',
                expect.objectContaining({
                    variant: 'intent_plus',
                    from: 'session_replay',
                    to: '/my-page',
                    kind: 'url',
                })
            )

            await expectLogic(logic).toMatchValues({
                effectiveTarget: { kind: 'url', value: '/my-page' },
            })
        })

        it('clearOverride removes localStorage entry and reverts to intent', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            window.localStorage.setItem(OVERRIDE_KEY, JSON.stringify({ kind: 'url', value: '/x' }))
            mountLogic()
            setFlagVariant('intent_plus')

            logic.actions.clearOverride()

            expect(window.localStorage.getItem(OVERRIDE_KEY)).toBeNull()
            await expectLogic(logic).toMatchValues({
                effectiveTarget: { kind: 'product', value: 'session_replay' },
            })
        })
    })

    describe('modal state', () => {
        it('opens and closes the configure modal', async () => {
            mountLogic()

            await expectLogic(logic).toMatchValues({ isConfigureModalOpen: false })

            logic.actions.showConfigureModal()
            await expectLogic(logic).toMatchValues({ isConfigureModalOpen: true })

            logic.actions.hideConfigureModal()
            await expectLogic(logic).toMatchValues({ isConfigureModalOpen: false })
        })

        it('seeds pending fields from effectiveTarget every time the modal opens', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            mountLogic()
            setFlagVariant('intent_plus')

            // First open: should reflect current product (session_replay), not the
            // initial reducer defaults that fired before afterMount finished.
            logic.actions.showConfigureModal()
            await expectLogic(logic).toMatchValues({
                pendingKind: 'product',
                pendingProduct: 'session_replay',
                pendingUrl: '',
            })

            // Override changes effectiveTarget — reopening should reflect the new state.
            logic.actions.setOverride({ kind: 'url', value: '/dashboards' })
            logic.actions.hideConfigureModal()
            logic.actions.showConfigureModal()
            await expectLogic(logic).toMatchValues({
                pendingKind: 'url',
                pendingProduct: 'product_analytics',
                pendingUrl: '/dashboards',
            })
        })
    })

    describe('team-scoped storage', () => {
        it('ignores values stored under a different team id', () => {
            // Simulate a different project's value lingering in this browser.
            window.localStorage.setItem(localStorageProductKey(MOCK_TEAM_ID + 1), 'session_replay')
            mountLogic()
            setFlagVariant('intent')

            // Current team has no stored intent, so falls through to APP_CONTEXT/null.
            expect(logic.values.promotedProductIntent).toBeNull()
        })

        it('writes the override under the current-team key, not a global one', () => {
            mountLogic()
            setFlagVariant('intent_plus')
            logic.actions.setOverride({ kind: 'url', value: '/x' })

            expect(window.localStorage.getItem(OVERRIDE_KEY)).toBe(JSON.stringify({ kind: 'url', value: '/x' }))
            // The legacy global key should not be touched.
            expect(window.localStorage.getItem('posthog-promoted-product-override')).toBeNull()
        })
    })
})
