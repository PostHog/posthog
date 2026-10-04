import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { toast } from '@posthog/quill'

import { writeToClipboard } from 'lib/utils/writeToClipboard'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { UserBasicType } from '~/types'

import { todaySessionMenuLogic } from './todaySessionMenuLogic'

jest.mock('lib/utils/writeToClipboard')

const colleague = { id: 2, uuid: 'user-2', first_name: 'Sam', email: 'sam@example.com' } as UserBasicType

describe('todaySessionMenuLogic', () => {
    let logic: ReturnType<typeof todaySessionMenuLogic.build>
    let requests: string[]
    let writesSucceed: boolean
    let failingIds: string[]
    let listLoads: number
    let warning: jest.SpyInstance

    beforeEach(async () => {
        requests = []
        writesSucceed = false
        failingIds = []
        listLoads = 0
        jest.mocked(posthog.capture).mockClear()
        warning = jest.spyOn(toast, 'warning').mockClear()
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/tasks/': () => {
                    listLoads++
                    return [200, { results: [], count: 0 }]
                },
            },
            patch: {
                '/api/projects/:team_id/tasks/:id/': async ({ params, request }) => {
                    requests.push(`patch ${params.id} ${JSON.stringify(await request.json())}`)
                    return writesSucceed && !failingIds.includes(String(params.id))
                        ? [200, {}]
                        : [500, { detail: 'Server error' }]
                },
            },
            post: {
                '/api/projects/:team_id/tasks/:id/pin/': async ({ params, request }) => {
                    requests.push(`pin ${params.id} ${JSON.stringify(await request.json())}`)
                    return writesSucceed && !failingIds.includes(String(params.id))
                        ? [200, {}]
                        : [500, { detail: 'Server error' }]
                },
                '/api/projects/:team_id/tasks/:id/handoff/': () => [400, { detail: 'Finish every run first.' }],
                '/api/projects/:team_id/tasks/:task_id/runs/:id/analyze/': () => [400, { error: 'No log yet.' }],
                '/api/projects/:team_id/tasks/:task_id/runs/:id/cancel/': ({ params }) => {
                    requests.push(`cancel ${params.task_id} ${params.id}`)
                    return writesSucceed ? [200, {}] : [409, { detail: 'Try later.' }]
                },
            },
        })
        initKeaTests()
        logic = todaySessionMenuLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        listLoads = 0
    })

    it.each([
        ['archive', () => logic.actions.archiveSession('task-1', true)],
        ['hand-off', () => logic.actions.handOffSession('task-1', colleague)],
        ['analysis', () => logic.actions.analyzeSession('task-1', 'run-1')],
        ['stop', () => logic.actions.stopSession('task-1', 'run-1')],
        ['archive confirm', () => logic.actions.confirmArchive('task-1', 'run-1')],
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
        expect(logic.values.sessionDialogOpen).toBe(true)
    })

    it('stops the run it is given and refreshes the lists', async () => {
        writesSucceed = true
        logic.actions.stopSession('task-1', 'run-2')
        await expectLogic(logic).toDispatchActions(['sessionUpdated', 'loadRecentTasks'])

        expect(requests).toEqual(['cancel task-1 run-2'])
    })

    it.each([
        ['a finished session archives straight away', null, null, ['patch task-1 {"archived":true}']],
        ['a running session asks first and writes nothing', 'run-1', 'menu-1', []],
    ])('%s', async (_, activeRunId, dialog, expected) => {
        writesSucceed = true
        logic.actions.requestArchive('task-1', 'menu-1', activeRunId)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.archiveConfirmMenuId).toEqual(dialog)
        expect(logic.values.sessionDialogOpen).toEqual(dialog !== null)
        expect(requests).toEqual(expected)
    })

    it('stops the run before it archives a running session once confirmed', async () => {
        writesSucceed = true
        logic.actions.requestArchive('task-1', 'menu-1', 'run-1')
        logic.actions.confirmArchive('task-1', 'run-1')
        await expectLogic(logic).toDispatchActions(['sessionUpdated', 'closeArchiveConfirm'])

        expect(requests).toEqual(['cancel task-1 run-1', 'patch task-1 {"archived":true}'])
        expect(logic.values.archiveConfirmMenuId).toBeNull()
    })

    it('keeps the confirm open and the session unarchived when the stop fails', async () => {
        logic.actions.requestArchive('task-1', 'menu-1', 'run-1')
        logic.actions.confirmArchive('task-1', 'run-1')
        await expectLogic(logic).toDispatchActions(['sessionUpdateFailed'])

        expect(logic.values.archiveConfirmMenuId).toEqual('menu-1')
    })

    it.each([
        [
            'pin',
            () => logic.actions.bulkSetSessionsPinned(['task-1', 'task-2', 'task-3', 'task-1'], true),
            (id: string) => `pin ${id} {"pinned":true}`,
            'today session pinned',
            'Couldn’t pin 1\u00a0session. Try again.',
        ],
        [
            'move',
            () => logic.actions.bulkMoveSessions(['task-1', 'task-2', 'task-3', 'task-1'], 'space-1'),
            (id: string) => `patch ${id} {"channel":"space-1"}`,
            'today session moved',
            'Couldn’t move 1\u00a0session. Try again.',
        ],
        [
            'archive',
            () => logic.actions.bulkArchiveSessions(['task-1', 'task-2', 'task-3', 'task-1'], true),
            (id: string) => `patch ${id} {"archived":true}`,
            'today session archived',
            'Couldn’t archive 1\u00a0session. Try again.',
        ],
    ])(
        'a bulk %s writes each session once, reloads the lists once, and reports the failures by count',
        async (_, run, request, event, failure) => {
            writesSucceed = true
            failingIds = ['task-2']
            run()
            expect(logic.values.pendingSessionIds).toEqual(['task-1', 'task-2', 'task-3'])
            await expectLogic(logic).toFinishAllListeners()

            expect([...requests].sort()).toEqual(['task-1', 'task-2', 'task-3'].map(request))
            expect(logic.values.pendingSessionIds).toEqual([])
            expect(listLoads).toEqual(2)
            expect(warning).toHaveBeenCalledTimes(1)
            expect(warning.mock.calls[0][0]).toMatchObject({ description: failure })
            expect(posthog.capture).toHaveBeenCalledWith(event, { bulk: true, session_count: 3, failed_count: 1 })
        }
    )

    it('restores only the sessions the bulk archive changed when the user clicks Undo', async () => {
        writesSucceed = true
        failingIds = ['task-2']
        logic.actions.bulkArchiveSessions(['task-1', 'task-2', 'task-3'], true)
        await expectLogic(logic).toFinishAllListeners()
        requests = []

        warning.mock.calls[0][0].action?.onClick()
        await expectLogic(logic).toFinishAllListeners()

        expect([...requests].sort()).toEqual(['patch task-1 {"archived":false}', 'patch task-3 {"archived":false}'])
    })

    it.each([
        ['pin', () => logic.actions.setSessionPinned('task-1', true), 'today session pinned'],
        ['move', () => logic.actions.moveSession('task-1', 'space-1'), 'today session moved'],
        ['archive', () => logic.actions.archiveSession('task-1', true), 'today session archived'],
    ])('reports a single %s as a one-session change', async (_, run, event) => {
        writesSucceed = true
        run()
        await expectLogic(logic).toFinishAllListeners()

        expect(posthog.capture).toHaveBeenCalledWith(event, { bulk: false, session_count: 1, failed_count: 0 })
    })

    it('copies the project-scoped session URL', async () => {
        jest.mocked(writeToClipboard).mockResolvedValue('copied')
        logic.actions.copySessionLink('task-1')
        await expectLogic(logic).toFinishAllListeners()

        expect(writeToClipboard).toHaveBeenCalledWith(`http://localhost/project/${MOCK_TEAM_ID}/ai?task=task-1`)
    })
})
