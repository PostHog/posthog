import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { todaySessionMenuLogic } from './todaySessionMenuLogic'
import { todaySpacesLogic } from './todaySpacesLogic'

describe('todaySessionMenuLogic', () => {
    let sessionSpace = 'space-a'
    let failPatch = false

    beforeEach(() => {
        sessionSpace = 'space-a'
        failPatch = false
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/tasks/': ({ request }) => {
                    const channel = new URL(request.url).searchParams.get('channel')
                    const results = channel === sessionSpace ? [{ id: 'task-1', title: 'Session', channel }] : []
                    return [200, { results, count: results.length }]
                },
            },
            patch: {
                '/api/projects/:team_id/tasks/:id/': async ({ request }) => {
                    if (failPatch) {
                        return [500, { detail: 'Server error' }]
                    }
                    const body = (await request.json()) as { channel?: string }
                    sessionSpace = body.channel ?? sessionSpace
                    return [200, { id: 'task-1', channel: sessionSpace }]
                },
            },
        })
        initKeaTests()
    })

    it('reloads every cached space after a move, so the session leaves its old space', async () => {
        const spaces = todaySpacesLogic()
        spaces.mount()
        const logic = todaySessionMenuLogic()
        logic.mount()
        spaces.actions.loadSpaceTasks('space-a')
        spaces.actions.loadSpaceTasks('space-b')
        await expectLogic(spaces).toFinishAllListeners()

        logic.actions.moveSession('task-1', 'space-b')
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(spaces).toFinishAllListeners()

        expect(spaces.values.spaceTasks['space-a']).toEqual([])
        expect(spaces.values.spaceTasks['space-b'].map((task) => task.id)).toEqual(['task-1'])
        expect(logic.values.pendingSessionIds).toEqual([])
    })

    it('clears the pending state when an update fails, so the menu works again', async () => {
        failPatch = true
        const logic = todaySessionMenuLogic()
        logic.mount()

        logic.actions.archiveSession('task-1', true)
        await expectLogic(logic).toDispatchActions(['archiveSession', 'sessionUpdateFailed'])

        expect(logic.values.pendingSessionIds).toEqual([])
    })
})
