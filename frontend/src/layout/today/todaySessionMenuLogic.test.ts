import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { UserBasicType } from '~/types'

import { todaySessionMenuLogic } from './todaySessionMenuLogic'

const colleague = { id: 2, uuid: 'user-2', first_name: 'Sam', email: 'sam@example.com' } as UserBasicType

describe('todaySessionMenuLogic', () => {
    let logic: ReturnType<typeof todaySessionMenuLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/tasks/': { results: [], count: 0 },
            },
            patch: {
                '/api/projects/:team_id/tasks/:id/': () => [500, { detail: 'Server error' }],
            },
            post: {
                '/api/projects/:team_id/tasks/:id/handoff/': () => [400, { detail: 'Finish every run first.' }],
                '/api/projects/:team_id/tasks/:task_id/runs/:id/analyze/': () => [400, { error: 'No log yet.' }],
            },
        })
        initKeaTests()
        logic = todaySessionMenuLogic()
        logic.mount()
    })

    it.each([
        ['archive', () => logic.actions.archiveSession('task-1', true)],
        ['hand-off', () => logic.actions.handOffSession('task-1', colleague)],
        ['analysis', () => logic.actions.analyzeSession('task-1', 'run-1')],
    ])('clears the pending state when the %s request fails, so the menu works again', async (_, run) => {
        run()
        await expectLogic(logic).toDispatchActions(['sessionUpdateFailed'])

        expect(logic.values.pendingSessionIds).toEqual([])
    })

    it('keeps the hand-off dialog open with the chosen person when the hand-off fails, so the user can retry', async () => {
        logic.actions.openHandoff('menu-1')
        logic.actions.setHandoffUser(colleague)
        logic.actions.handOffSession('task-1', colleague)
        await expectLogic(logic).toDispatchActions(['sessionUpdateFailed'])

        expect(logic.values.handoffMenuId).toEqual('menu-1')
        expect(logic.values.handoffUser).toEqual(colleague)
    })
})
