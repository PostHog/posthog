import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { initKeaTests } from '~/test/init'

import { aiShellLogic } from './aiShellLogic'

describe('aiShellLogic', () => {
    let logic: ReturnType<typeof aiShellLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        logic = aiShellLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        localStorage.clear()
    })

    describe('isMaxAvailable selector', () => {
        it.each([
            { realm: 'a not-yet-loaded preflight', preflight: null, expected: true },
            { realm: 'PostHog Cloud', preflight: { cloud: true }, expected: true },
            {
                realm: 'self-hosted with an Anthropic key',
                preflight: { cloud: false, is_debug: false, anthropic_available: true },
                expected: true,
            },
            {
                realm: 'self-hosted without a key',
                preflight: { cloud: false, is_debug: false, anthropic_available: false },
                expected: false,
            },
        ])('is $expected on $realm', async ({ preflight, expected }) => {
            preflightLogic.actions.loadPreflightSuccess(preflight as any)

            await expectLogic(logic).toMatchValues({ isMaxAvailable: expected })
        })
    })

    // The flag is the only thing that may expose the new posthog_ai surface — without the gate a stored
    // preference (or a missing default) would leak it to every user. Lock in: flag off collapses to legacy
    // regardless of the stored mode; flag on passes the stored mode through.
    describe('effectivePhaiView selector', () => {
        it.each([
            { flagOn: false, mode: 'new', expected: 'legacy' },
            { flagOn: false, mode: 'legacy', expected: 'legacy' },
            { flagOn: true, mode: 'new', expected: 'new' },
            { flagOn: true, mode: 'legacy', expected: 'legacy' },
        ] as const)(
            'is $expected when sandbox flag is $flagOn and stored mode is $mode',
            async ({ flagOn, mode, expected }) => {
                featureFlagLogic.actions.setFeatureFlags(
                    flagOn ? [FEATURE_FLAGS.PHAI_SANDBOX_MODE] : [],
                    flagOn ? { [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true } : {}
                )
                logic.actions.setPhaiViewMode(mode)

                await expectLogic(logic).toMatchValues({ effectivePhaiView: expected })
            }
        )
    })

    // Users already chose a view under this key. A renamed key, or a second persisted reducer that wins
    // the race, would silently reset that choice.
    it.each(['new', 'legacy'] as const)('restores the view mode %s saved under the existing key', (mode) => {
        logic.unmount()
        initKeaTests()
        localStorage.setItem('posthog_ai_view_mode', JSON.stringify(mode))

        logic = aiShellLogic()
        logic.mount()

        expect(logic.values.phaiViewMode).toBe(mode)
    })
})
