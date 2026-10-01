import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { canvasSceneLogic } from './canvasSceneLogic'

const CANVAS_ID = 'canvas-1'

describe('canvasSceneLogic', () => {
    let releaseTaskRequest: () => void = () => {}

    beforeEach(() => {
        const taskRequestReleased = new Promise<void>((resolve) => {
            releaseTaskRequest = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/canvases/:id/view/': {
                    canvas: {
                        id: CANVAS_ID,
                        name: 'Untitled canvas',
                        kind: 'freeform',
                        channel: 'space-1',
                        template_id: 'freeform',
                        generation_task_id: null,
                        published_build_id: null,
                    },
                    published_build: null,
                    current_version_id: null,
                    has_active_build: false,
                    source: null,
                    layout: null,
                    sandbox_document_url: null,
                },
                '/api/projects/:team_id/canvases/:id/builds/': { builds: [], published_build_id: null },
                '/api/projects/:team_id/task_channels/:id/': { id: 'space-1', name: 'me', system_role: 'personal' },
            },
            post: {
                '/api/projects/:team_id/tasks/': async () => {
                    await taskRequestReleased
                    return [403, { error: 'Agent-started task runs are not available for this project' }]
                },
            },
        })
        initKeaTests()
    })

    it('keeps the composer on screen while a run starts and after it fails to start', async () => {
        const logic = canvasSceneLogic({ id: CANVAS_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadViewSuccess'])
        expect(logic.values.bodyState).toEqual('empty')

        logic.actions.generateCanvas('A chart of daily signups', false)
        expect(logic.values.generationStarting).toBe(true)
        expect(logic.values.bodyState).toEqual('empty')

        releaseTaskRequest()
        await expectLogic(logic).toDispatchActions(['generationFinished'])
        expect(logic.values.bodyState).toEqual('empty')
    })
})
