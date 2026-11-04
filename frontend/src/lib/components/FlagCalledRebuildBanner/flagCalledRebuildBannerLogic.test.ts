import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { initKeaTests } from '~/test/init'

import { announcementUrlFromPayload, flagCalledRebuildBannerLogic } from './flagCalledRebuildBannerLogic'

describe('flagCalledRebuildBannerLogic', () => {
    let logic: ReturnType<typeof flagCalledRebuildBannerLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = flagCalledRebuildBannerLogic()
        logic.mount()
    })

    it.each([
        ['off', FlagEvaluationsModeEnumApi.Number1, false],
        ['on', FlagEvaluationsModeEnumApi.Number0, false],
        ['on', FlagEvaluationsModeEnumApi.Number1, true],
        ['on', FlagEvaluationsModeEnumApi.Number2, true],
    ])('with the flag %s on mode %s, banners enabled: %s', (flagState, mode, expected) => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.FLAG_CALLED_MOVE_NOTICES]: flagState === 'on',
        })
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, flag_evaluations_mode: mode })

        expect(logic.values.bannersEnabled).toBe(expected)
    })

    it.each([
        ['no payload', undefined, null],
        ['a null url', { url: null }, null],
        ['text that is not a URL', { url: 'the announcement' }, null],
        ['a javascript URL', { url: 'javascript:alert(1)' }, null],
        ['an http URL', { url: 'http://posthog.com/blog/flag-calls' }, null],
        ['an https URL', { url: 'https://posthog.com/blog/flag-calls' }, 'https://posthog.com/blog/flag-calls'],
    ])('a payload with %s links to %s', (_label, payload, expected) => {
        expect(announcementUrlFromPayload(payload)).toBe(expected)
    })
})
