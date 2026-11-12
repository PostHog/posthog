import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'

import { initKeaTests } from '~/test/init'
import type { AppContext } from '~/types'

import {
    areClientFeatureFlagsHonored,
    deriveFeatureFlags,
    featureFlagLogic,
    getPersistedFeatureFlags,
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

    describe('deriveFeatureFlags', () => {
        it.each([
            [
                'turns the scene menu bar on with today-rail-nav',
                { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true },
                undefined,
                { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true, [FEATURE_FLAGS.SCENE_MENU_BAR]: true },
            ],
            [
                'keeps the scene menu bar on by its own flag',
                { [FEATURE_FLAGS.SCENE_MENU_BAR]: true },
                undefined,
                { [FEATURE_FLAGS.SCENE_MENU_BAR]: true },
            ],
            [
                'leaves the scene menu bar off without either flag',
                { [FEATURE_FLAGS.TODAY_RAIL_NAV]: false },
                undefined,
                { [FEATURE_FLAGS.TODAY_RAIL_NAV]: false },
            ],
            [
                'turns PostHog AI 2.0 off when access is denied',
                { [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true },
                false,
                { [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: false },
            ],
            [
                'keeps the PostHog AI 2.0 flag without an access decision',
                { [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true },
                undefined,
                { [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true },
            ],
        ])('%s', (_name, flags, posthogAiAccess, expected) => {
            expect(deriveFeatureFlags(flags, posthogAiAccess)).toEqual(expected)
        })
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
