import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { flagCalledRebuildBannerLogic } from './flagCalledRebuildBannerLogic'

describe('flagCalledRebuildBannerLogic', () => {
    let logic: ReturnType<typeof flagCalledRebuildBannerLogic.build>
    let releaseFirstAction: () => void

    beforeEach(() => {
        const firstActionHeld = new Promise<void>((resolve) => {
            releaseFirstAction = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team/actions/1/': async () => {
                    await firstActionHeld
                    return [200, { id: 1, steps: [{ event: '$feature_flag_called' }] }]
                },
                '/api/projects/:team/actions/2/': () => [200, { id: 2, steps: [{ event: '$feature_flag_called' }] }],
                '/api/projects/:team/actions/3/': () => [404, { detail: 'Not found.' }],
            },
        })
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
            [FEATURE_FLAGS.FLAG_CALLED_REBUILD_BANNERS]: flagState === 'on',
        })
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, flag_evaluations_mode: mode })

        expect(logic.values.bannersEnabled).toBe(expected)
    })

    it('keeps the actions of a load that finishes before an earlier one', async () => {
        logic.actions.loadReferencedActions([1])
        logic.actions.loadReferencedActions([2, 3])
        await expectLogic(logic).toDispatchActions(['addReferencedActions'])

        releaseFirstAction()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.referencedActions.map((action) => action.id).sort()).toEqual([1, 2])
    })
})
