import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as taskApi from '../../canvasTasksApi'
import * as canvasApi from '../../generated/api'
import { canvasSceneLogic } from '../../scene/canvasSceneLogic'
import { canvasChatLogic } from './canvasChatLogic'

describe('canvasChatLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/canvases/:id/view/': {
                    canvas: { id: 'canvas', kind: 'freeform', generation_task_id: null },
                    current_version_id: null,
                    published_build: null,
                    has_active_build: false,
                },
                '/api/projects/:team_id/canvases/:id/builds/': { builds: [], published_build_id: null },
                '/api/projects/:team_id/canvases/:id/versions/': { results: [], next: null },
                '/api/projects/:team_id/canvases/:id/drafts/': [],
            },
        })
        initKeaTests()
    })

    afterEach(() => jest.restoreAllMocks())

    it('keeps a resumed run tracked when the canvas link fails', async () => {
        const finished: taskApi.CanvasGenerationTask = {
            id: 'task',
            title: 'Canvas task',
            latest_run: { id: 'old-run', status: 'completed' },
        }
        const resumed: taskApi.CanvasGenerationTask = {
            ...finished,
            latest_run: { id: 'new-run', status: 'queued' },
        }
        jest.spyOn(taskApi, 'loadCanvasGenerationTask').mockResolvedValue(finished)
        const resume = jest.spyOn(taskApi, 'resumeCanvasTask').mockResolvedValue(resumed)
        jest.spyOn(canvasApi, 'canvasesPartialUpdate').mockRejectedValue(new Error('Link failed'))
        const logic = canvasChatLogic({ id: 'canvas' })
        logic.mount()
        await expectLogic(canvasSceneLogic({ id: 'canvas' })).toDispatchActions(['loadViewSuccess'])
        await expectLogic(logic, () => logic.actions.taskStarted('task')).toDispatchActions(['loadOwnTaskSuccess'])
        logic.actions.setDraft('Add a chart')
        await expectLogic(logic, () => logic.actions.sendMessage()).toDispatchActions(['sendFinished'])
        expect(logic.values.draft).toBe('')
        expect(logic.values.chatRun?.id).toBe('new-run')
        expect(logic.values.sending).toBe(false)
        logic.actions.sendMessage()
        expect(resume).toHaveBeenCalledTimes(1)
    })

    it('resumes the run when a follow-up reaches a run that has already ended', async () => {
        const live: taskApi.CanvasGenerationTask = {
            id: 'task',
            title: 'Canvas task',
            latest_run: { id: 'old-run', status: 'in_progress' },
        }
        const resumed: taskApi.CanvasGenerationTask = {
            ...live,
            latest_run: { id: 'new-run', status: 'queued' },
        }
        jest.spyOn(taskApi, 'loadCanvasGenerationTask').mockResolvedValue(live)
        const send = jest
            .spyOn(taskApi, 'sendCanvasRunMessage')
            .mockRejectedValue(new ApiError('Task run workflow has ended', 409))
        const resume = jest.spyOn(taskApi, 'resumeCanvasTask').mockResolvedValue(resumed)
        jest.spyOn(canvasApi, 'canvasesPartialUpdate').mockRejectedValue(new Error('Link failed'))
        const logic = canvasChatLogic({ id: 'canvas' })
        logic.mount()
        await expectLogic(canvasSceneLogic({ id: 'canvas' })).toDispatchActions(['loadViewSuccess'])
        await expectLogic(logic, () => logic.actions.taskStarted('task')).toDispatchActions(['loadOwnTaskSuccess'])
        logic.actions.setDraft('Carry on')
        await expectLogic(logic, () => logic.actions.sendMessage()).toDispatchActions(['sendFinished'])
        expect(send).toHaveBeenCalledWith(expect.any(String), 'task', 'old-run', 'Carry on')
        expect(resume).toHaveBeenCalledWith(expect.any(String), 'task', {
            resumeFromRunId: 'old-run',
            message: 'Carry on',
        })
        expect(logic.values.sendError).toBeNull()
        expect(logic.values.chatRun?.id).toBe('new-run')
    })

    it('shows the error when a follow-up fails for another reason', async () => {
        jest.spyOn(taskApi, 'loadCanvasGenerationTask').mockResolvedValue({
            id: 'task',
            title: 'Canvas task',
            latest_run: { id: 'old-run', status: 'in_progress' },
        })
        jest.spyOn(taskApi, 'sendCanvasRunMessage').mockRejectedValue(new ApiError('Agent server unreachable', 502))
        const resume = jest.spyOn(taskApi, 'resumeCanvasTask')
        const logic = canvasChatLogic({ id: 'canvas' })
        logic.mount()
        await expectLogic(canvasSceneLogic({ id: 'canvas' })).toDispatchActions(['loadViewSuccess'])
        await expectLogic(logic, () => logic.actions.taskStarted('task')).toDispatchActions(['loadOwnTaskSuccess'])
        logic.actions.setDraft('Carry on')
        await expectLogic(logic, () => logic.actions.sendMessage()).toDispatchActions(['sendFinished'])
        expect(resume).not.toHaveBeenCalled()
        expect(logic.values.sendError).toBe('Agent server unreachable')
    })
})
