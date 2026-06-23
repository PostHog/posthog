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
        ])('variant=%s -> shouldRenderEntry=%s shouldRenderCog=%s', async (variant, renderEntry, renderCog) => {
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

        it('falls back to dashboards when no intent is available', async () => {
            mountLogic()
            setFlagVariant('intent')

            await expectLogic(logic).toMatchValues({
                effectiveProductKey: 'dashboards',
                shouldRenderEntry: true,
            })
        })
    })

    describe('effectiveProductKey', () => {
        it('resolves from localStorage when set', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'web_analytics')
            mountLogic()
            setFlagVariant('intent')

            await expectLogic(logic).toMatchValues({ effectiveProductKey: 'web_analytics' })
        })

        it('intent_plus prefers override over onboarding intent', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            window.localStorage.setItem(OVERRIDE_KEY, 'web_analytics')
            mountLogic()
            setFlagVariant('intent_plus')

            await expectLogic(logic).toMatchValues({ effectiveProductKey: 'web_analytics' })
        })

        it('intent variant ignores the override (cog is intent_plus only)', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            window.localStorage.setItem(OVERRIDE_KEY, 'web_analytics')
            mountLogic()
            setFlagVariant('intent')

            await expectLogic(logic).toMatchValues({ effectiveProductKey: 'session_replay' })
        })

        it('falls back to dashboards for an unknown product key', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'fictional_product')
            mountLogic()
            setFlagVariant('intent')

            await expectLogic(logic).toMatchValues({
                effectiveProductKey: 'dashboards',
                shouldRenderEntry: true,
            })
        })

        it('ignores an unknown override', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            window.localStorage.setItem(OVERRIDE_KEY, 'not_a_product')
            mountLogic()
            setFlagVariant('intent_plus')

            await expectLogic(logic).toMatchValues({ effectiveProductKey: 'session_replay' })
        })
    })

    describe('defaultProductKey', () => {
        it.each([
            ['web_analytics', 'web_analytics'],
            ['fictional_product', 'dashboards'],
        ])('intent=%s -> defaultProductKey=%s', async (intent, expected) => {
            window.localStorage.setItem(PRODUCT_KEY, intent)
            mountLogic()
            setFlagVariant('intent_plus')

            await expectLogic(logic).toMatchValues({ defaultProductKey: expected })
        })

        it('falls back to dashboards with no intent', async () => {
            mountLogic()
            setFlagVariant('intent_plus')

            await expectLogic(logic).toMatchValues({ defaultProductKey: 'dashboards' })
        })
    })

    describe('tracking', () => {
        it('captures click with the product key', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            mountLogic()
            setFlagVariant('intent')

            logic.actions.trackPromotedProductClick()

            expect(mockedPosthog.capture).toHaveBeenCalledWith(
                'promoted product clicked',
                expect.objectContaining({ variant: 'intent', product_key: 'session_replay' })
            )
        })

        it('does not capture click for a non-entry variant', async () => {
            mountLogic()
            setFlagVariant('control')

            logic.actions.trackPromotedProductClick()

            expect(mockedPosthog.capture).not.toHaveBeenCalledWith('promoted product clicked', expect.anything())
        })

        it('captures config opened with the current product', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            mountLogic()
            setFlagVariant('intent_plus')

            logic.actions.showConfigureModal()

            expect(mockedPosthog.capture).toHaveBeenCalledWith(
                'promoted product config opened',
                expect.objectContaining({ variant: 'intent_plus', current_product: 'session_replay' })
            )
        })

        it('persists override to localStorage and captures config changed', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            mountLogic()
            setFlagVariant('intent_plus')

            logic.actions.setOverride('web_analytics', logic.values.effectiveProductKey)

            expect(window.localStorage.getItem(OVERRIDE_KEY)).toBe('web_analytics')
            expect(mockedPosthog.capture).toHaveBeenCalledWith(
                'promoted product config changed',
                expect.objectContaining({ variant: 'intent_plus', from: 'session_replay', to: 'web_analytics' })
            )

            await expectLogic(logic).toMatchValues({ effectiveProductKey: 'web_analytics' })
        })

        it('captures the product showing at change time as `from` on repeated overrides', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            mountLogic()
            setFlagVariant('intent_plus')

            logic.actions.setOverride('web_analytics', logic.values.effectiveProductKey)
            logic.actions.setOverride('feature_flags', logic.values.effectiveProductKey)

            expect(mockedPosthog.capture).toHaveBeenLastCalledWith(
                'promoted product config changed',
                expect.objectContaining({ from: 'web_analytics', to: 'feature_flags' })
            )
        })

        it('clearOverride removes localStorage entry, reverts to intent, and reports the change', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            window.localStorage.setItem(OVERRIDE_KEY, 'web_analytics')
            mountLogic()
            setFlagVariant('intent_plus')

            logic.actions.clearOverride(logic.values.effectiveProductKey)

            expect(window.localStorage.getItem(OVERRIDE_KEY)).toBeNull()
            expect(mockedPosthog.capture).toHaveBeenCalledWith(
                'promoted product config changed',
                expect.objectContaining({ from: 'web_analytics', to: 'session_replay' })
            )
            await expectLogic(logic).toMatchValues({ effectiveProductKey: 'session_replay' })
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

        it('seeds the pending product from effectiveProductKey every time the modal opens', async () => {
            window.localStorage.setItem(PRODUCT_KEY, 'session_replay')
            mountLogic()
            setFlagVariant('intent_plus')

            logic.actions.showConfigureModal()
            await expectLogic(logic).toMatchValues({ pendingProduct: 'session_replay' })

            logic.actions.setOverride('web_analytics', logic.values.effectiveProductKey)
            logic.actions.hideConfigureModal()
            logic.actions.showConfigureModal()
            await expectLogic(logic).toMatchValues({ pendingProduct: 'web_analytics' })
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
            logic.actions.setOverride('web_analytics', logic.values.effectiveProductKey)

            expect(window.localStorage.getItem(OVERRIDE_KEY)).toBe('web_analytics')
            // The legacy global key should not be touched.
            expect(window.localStorage.getItem('posthog-promoted-product-override')).toBeNull()
        })
    })
})
