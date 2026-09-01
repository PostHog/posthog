import { FEATURE_FLAGS } from 'lib/constants'

import type { AppContext } from '~/types'

import { areClientFeatureFlagsHonored, getPersistedFeatureFlags } from './featureFlagLogic'

describe('areClientFeatureFlagsHonored', () => {
    it.each([
        [null, false],
        [{ cloud: false, is_debug: false }, false],
        [{ cloud: true, is_debug: false }, true],
        [{ cloud: false, is_debug: true }, true],
        [{ cloud: true, is_debug: true }, true],
    ])('preflight %s returns %s', (preflight, expected) => {
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
