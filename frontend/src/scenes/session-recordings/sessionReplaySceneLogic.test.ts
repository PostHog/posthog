import { expectLogic } from 'kea-test-utils'

import { sessionReplaySceneLogic } from 'scenes/session-recordings/sessionReplaySceneLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

describe('sessionReplaySceneLogic', () => {
    let logic: ReturnType<typeof sessionReplaySceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = sessionReplaySceneLogic()
    })

    it('refreshes currentTeam on mount so a stale session_recording_opt_in cannot linger', async () => {
        logic.mount()
        // currentTeam is otherwise only seeded once from app context at boot, so a tab left open
        // across a session_recording_opt_in change would show a stale "not enabled" banner
        await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeam', 'loadCurrentTeamSuccess'])
        expect(teamLogic.values.currentTeam).not.toBeNull()
    })
})
