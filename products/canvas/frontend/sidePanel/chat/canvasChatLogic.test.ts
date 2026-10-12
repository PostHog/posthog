import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as taskApi from '../../canvasTasksApi'
import * as canvasApi from '../../generated/api'
import { canvasSceneLogic } from '../../scene/canvasSceneLogic'
import { canvasChatLogic } from './canvasChatLogic'

describe('canvasChatLogic', () => {
    afterEach(() => jest.restoreAllMocks())

    it('keeps a resumed run tracked when the canvas link fails', async () => {
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
})
