import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { todaySessionMenuLogic } from './todaySessionMenuLogic'

describe('todaySessionMenuLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/tasks/': { results: [], count: 0 },
            },
            patch: {
                '/api/projects/:team_id/tasks/:id/': () => [500, { detail: 'Server error' }],
            },
        })
        initKeaTests()
    })

    it('clears the pending state when an update fails, so the menu works again', async () => {
        const logic = todaySessionMenuLogic()
        logic.mount()

        logic.actions.archiveSession('task-1', true)
        await expectLogic(logic).toDispatchActions(['archiveSession', 'sessionUpdateFailed'])

        expect(logic.values.pendingSessionIds).toEqual([])
    })
})
