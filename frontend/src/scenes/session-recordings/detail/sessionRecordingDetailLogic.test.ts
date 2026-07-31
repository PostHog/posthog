import { expectLogic } from 'kea-test-utils'

import { sessionRecordingDetailLogic } from 'scenes/session-recordings/detail/sessionRecordingDetailLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

describe('sessionRecordingDetailLogic', () => {
    let logic: ReturnType<typeof sessionRecordingDetailLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = sessionRecordingDetailLogic({ id: 'session-id' })
    })

    it('refreshes currentTeam on mount so a stale session_recording_opt_in cannot linger', async () => {
        logic.mount()
        // currentTeam is otherwise only seeded once from app context at boot, so landing on this
        // page after session_recording_opt_in changed elsewhere would show a stale "not enabled" banner
        await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeam', 'loadCurrentTeamSuccess'])
        expect(teamLogic.values.currentTeam).not.toBeNull()
    })
})
