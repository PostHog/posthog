import posthog from 'posthog-js'

import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'

import { initKeaTests } from '~/test/init'
import type { AppContext } from '~/types'

import {
    areClientFeatureFlagsHonored,
    featureFlagLogic,
    getPersistedFeatureFlags,
    peekFeatureFlag,
} from './featureFlagLogic'

describe('featureFlagLogic', () => {
    describe('areClientFeatureFlagsHonored', () => {
        afterEach(() => {
            delete window.JS_POSTHOG_SELF_CAPTURE
        })

        it.each([
            [null, false, false],
            [{ cloud: false, is_debug: false }, false, false],
            [{ cloud: true, is_debug: false }, false, true],
            [{ cloud: false, is_debug: true }, false, true],
            [{ cloud: true, is_debug: true }, false, true],
            [{ cloud: false, is_debug: false }, true, true],
            [null, true, true],
        ])('preflight %s with self-capture %s returns %s', (preflight, selfCapture, expected) => {
            window.JS_POSTHOG_SELF_CAPTURE = selfCapture
            expect(areClientFeatureFlagsHonored(preflight)).toBe(expected)
        })
    })

    describe('getPersistedFeatureFlags', () => {
        it('maps server-persisted flags to the enabled frontend baseline', () => {
            const appContext = {
                persisted_feature_flags: [FEATURE_FLAGS.WAREHOUSE_PERSON_PROPERTIES],
            } as AppContext

            expect(getPersistedFeatureFlags(appContext)).toEqual({
                [FEATURE_FLAGS.WAREHOUSE_PERSON_PROPERTIES]: true,
            })
        })
    })

    describe('scene menu bar', () => {
        it.each([
            ['on with today-rail-nav', { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true }, true],
            ['on by its own flag', { [FEATURE_FLAGS.SCENE_MENU_BAR]: true }, true],
            ['off without either flag', { [FEATURE_FLAGS.TODAY_RAIL_NAV]: false }, undefined],
        ])('is %s', (_name, variants, expected) => {
            initKeaTests()
            const logic = featureFlagLogic()
            logic.mount()

            logic.actions.setFeatureFlags(Object.keys(variants), variants)

            expect(logic.values.featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]).toBe(expected)
        })
    })

    describe('flags from posthog-js', () => {
        const FLAG = 'flag-created-after-the-last-visit'

        afterEach(() => {
            delete window.POSTHOG_USER_IDENTITY_WITH_FLAGS
            jest.mocked(posthog.onFeatureFlags).mockImplementation(() => () => {})
            jest.mocked(posthog.get_property).mockReset()
        })

        it.each([
            ['a failed load keeps a flag the page decided on', true, { [FLAG]: true }, {}, {}, true],
            [
                'a failed load turns off a stored flag the page decided off',
                true,
                { [FLAG]: false },
                { [FLAG]: true },
                {},
                undefined,
            ],
            ['a failed load keeps a stored flag the page left undecided', true, {}, { [FLAG]: true }, {}, true],
            [
                'a failed load keeps an early access opt-out',
                true,
                { [FLAG]: true },
                {},
                { $stored_person_properties: { [`$feature_enrollment/${FLAG}`]: false } },
                undefined,
            ],
            [
                'a failed load keeps a local override',
                true,
                { [FLAG]: true },
                {},
                { $override_feature_flags: { [FLAG]: false } },
                undefined,
            ],
            ['a successful load ignores the page decision', false, { [FLAG]: true }, {}, {}, undefined],
        ])(
            '%s',
            (_name, errorsLoading, pageFlags, loadedVariants, storedProperties: Record<string, unknown>, expected) => {
                window.POSTHOG_USER_IDENTITY_WITH_FLAGS = { featureFlags: pageFlags }
                jest.mocked(posthog.get_property).mockImplementation((key) => storedProperties[key])
                jest.mocked(posthog.onFeatureFlags).mockImplementation((callback) => {
                    callback(Object.keys(loadedVariants), loadedVariants, { errorsLoading })
                    return () => {}
                })
                initKeaTests()

                const logic = featureFlagLogic()
                logic.mount()

                expect(peekFeatureFlag(logic.values.featureFlags, FLAG as FeatureFlagKey)).toBe(expected)
            }
        )
    })

    describe('receivedFeatureFlags', () => {
        afterEach(() => {
            delete (posthog as any).config
        })

        // The mocked onFeatureFlags never calls back, as posthog-js does not when flags are off.
        it.each([
            ['flags disabled', { advanced_disable_flags: true }, true],
            ['flags enabled', { advanced_disable_flags: false }, false],
        ])('with %s is %s before any flags arrive', (_name, config, expected) => {
            ;(posthog as any).config = config
            initKeaTests()

            const logic = featureFlagLogic()
            logic.mount()

            expect(logic.values.receivedFeatureFlags).toBe(expected)
        })
    })
})
