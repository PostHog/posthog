import { MOCK_USER_UUID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { canvasSceneLogic } from './canvasSceneLogic'

const CANVAS_ID = 'canvas-1'

describe('canvasSceneLogic', () => {
    let releaseTaskRequest: () => void = () => {}
    let patchStatus = 200
    let patchedBody: Record<string, unknown> | null = null

    beforeEach(() => {
        const taskRequestReleased = new Promise<void>((resolve) => {
            releaseTaskRequest = resolve
        })
        patchStatus = 200
        patchedBody = null
        const spaces = {
            'space-1': { id: 'space-1', name: 'me', system_role: 'personal', channel_type: 'personal' },
            'space-team': { id: 'space-team', name: 'general', system_role: 'general', channel_type: 'public' },
        }
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
                '/api/projects/:team_id/task_channels/': Object.values(spaces),
                '/api/projects/:team_id/task_channels/:id/': (req) => [
                    200,
                    spaces[req.params.id as keyof typeof spaces],
                ],
            },
            patch: {
                '/api/projects/:team_id/canvases/:id/': async ({ request }) => {
                    patchedBody = (await request.json()) as Record<string, unknown>
                    return patchStatus === 200
                        ? [
                              200,
                              {
                                  id: CANVAS_ID,
                                  name: 'Untitled canvas',
                                  kind: 'freeform',
                                  channel: patchedBody.channel_id,
                              },
                          ]
                        : [patchStatus, { detail: 'Only the canvas creator can rename, move, pin, or describe it.' }]
                },
            },
            post: {
                '/api/projects/:team_id/tasks/:id/run/': [
                    201,
                    { id: 'task-1', title: 'Daily signups', latest_run: { status: 'queued' } },
                ],
                '/api/projects/:team_id/tasks/': async () => {
                    await taskRequestReleased
                    return [403, { error: 'Agent-started task runs are not available for this project' }]
                },
            },
        })
        initKeaTests()
    })

    it.each([
        ['moves the canvas to the team space', 200, 'public'],
        ['keeps the canvas where it was when the move fails', 403, 'private'],
    ])('Make public %s', async (_, status, visibility) => {
        patchStatus = status
        const logic = canvasSceneLogic({ id: CANVAS_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadViewSuccess', 'loadSpaceSuccess'])
        expect(logic.values.visibility).toEqual('private')

        logic.actions.openMakePublic()
        logic.actions.setCanvasVisibility('public')
        await expectLogic(logic).toDispatchActions(['canvasVisibilityChanged'])
        await expectLogic(logic).toFinishAllListeners()

        expect(patchedBody).toEqual({ channel_id: 'space-team' })
        expect(logic.values.visibility).toEqual(visibility)
        expect(logic.values.visibilityChanging).toBe(false)
        expect(logic.values.makePublicOpen).toBe(false)
    })

    it.each([
        ['moves the creator’s chats first and leaves a teammate’s chat alone', 200],
        ['moves the chats back when the canvas cannot move', 403],
    ])('Make private %s', async (_, canvasStatus) => {
        const order: string[] = []
        const tasksPatched: Record<string, unknown[]> = {}
        const me = { id: 1, uuid: MOCK_USER_UUID }
        useMocks({
            get: {
                '/api/projects/:team_id/canvases/:id/view/': {
                    canvas: {
                        id: CANVAS_ID,
                        name: 'Weekly active users',
                        kind: 'freeform',
                        channel: 'space-team',
                        generation_task_id: 'task-authoring',
                        created_by: me,
                    },
                    published_build: null,
                    current_version_id: null,
                    has_active_build: false,
                    source: null,
                    layout: null,
                    sandbox_document_url: null,
                },
                // An earlier run that failed before it made a version is found by the canvas id in its prompt.
                '/api/projects/:team_id/tasks/': { next: null, results: [{ id: 'task-failed-run' }] },
                '/api/projects/:team_id/tasks/:id/': ({ params }) => [
                    200,
                    {
                        id: params.id,
                        title: 'Weekly active users',
                        latest_run: null,
                        created_by: me,
                        channel: 'space-team',
                    },
                ],
                '/api/projects/:team_id/canvases/:id/versions/': {
                    next: null,
                    results: [
                        { id: 'version-2', task_id: 'task-follow-up', created_by: me },
                        { id: 'version-3', task_id: 'task-teammate', created_by: { id: 2, uuid: 'teammate-uuid' } },
                    ],
                },
            },
            patch: {
                '/api/projects/:team_id/tasks/:id/': async ({ params, request }) => {
                    order.push(`task:${params.id}`)
                    tasksPatched[params.id as string] = [
                        ...(tasksPatched[params.id as string] ?? []),
                        await request.json(),
                    ]
                    return [200, { id: params.id }]
                },
                '/api/projects/:team_id/canvases/:id/': async ({ request }) => {
                    order.push('canvas')
                    patchedBody = (await request.json()) as Record<string, unknown>
                    return canvasStatus === 200
                        ? [
                              200,
                              {
                                  id: CANVAS_ID,
                                  name: 'Weekly active users',
                                  kind: 'freeform',
                                  channel: patchedBody.channel_id,
                                  created_by: me,
                              },
                          ]
                        : [canvasStatus, { detail: 'Only the canvas creator can rename, move, pin, or describe it.' }]
                },
            },
        })
        userLogic.mount()
        await expectLogic(userLogic).toDispatchActions(['loadUserSuccess'])
        const logic = canvasSceneLogic({ id: CANVAS_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadViewSuccess', 'loadSpaceSuccess'])
        expect(logic.values.visibility).toEqual('public')

        logic.actions.setCanvasVisibility('private')
        await expectLogic(logic).toDispatchActions(['canvasVisibilityChanged'])

        const toPersonal = { channel: 'space-1' }
        const back = { channel: 'space-team' }
        const expected = canvasStatus === 200 ? [toPersonal] : [toPersonal, back]
        expect(tasksPatched).toEqual({
            'task-failed-run': expected,
            'task-follow-up': expected,
            'task-authoring': expected,
        })
        expect(order.indexOf('canvas')).toBeGreaterThan(order.indexOf('task:task-authoring'))
        expect(logic.values.canvas?.channel).toEqual(canvasStatus === 200 ? 'space-1' : 'space-team')
    })

    it('Undo after Make private moves the canvas back first, then its chats', async () => {
        const order: string[] = []
        useMocks({
            patch: {
                '/api/projects/:team_id/tasks/:id/': async ({ params, request }) => {
                    order.push(`task:${params.id}:${((await request.json()) as { channel: string }).channel}`)
                    return [200, { id: params.id }]
                },
                '/api/projects/:team_id/canvases/:id/': async ({ request }) => {
                    patchedBody = (await request.json()) as Record<string, unknown>
                    order.push(`canvas:${patchedBody.channel_id}`)
                    return [
                        200,
                        { id: CANVAS_ID, name: 'Untitled canvas', kind: 'freeform', channel: patchedBody.channel_id },
                    ]
                },
            },
        })
        const logic = canvasSceneLogic({ id: CANVAS_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadViewSuccess', 'loadSpaceSuccess'])

        logic.actions.moveCanvasToSpace('space-team', null, false, [{ id: 'task-authoring', from: 'space-team' }])
        await expectLogic(logic).toDispatchActions(['canvasVisibilityChanged'])

        expect(order).toEqual(['canvas:space-team', 'task:task-authoring:space-team'])
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
        // The side panel and the composer say why, rather than only a toast that disappears.
        expect(logic.values.generationError).toEqual('Agent-started task runs are not available for this project')
    })

    it('stops generating when the agent turn ends while the cloud run stays open', async () => {
        const logic = canvasSceneLogic({ id: CANVAS_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadViewSuccess'])
        logic.actions.canvasUpdated({ ...logic.values.canvas!, generation_task_id: 'task-1' })
        logic.actions.loadGenerationTaskSuccess({
            id: 'task-1',
            title: 'Daily signups',
            latest_run: { id: 'run-1', status: 'in_progress' },
        })
        expect(logic.values.isGenerating).toBe(true)

        logic.actions.setAgentTurn('run-1', false)
        expect(logic.values.isGenerating).toBe(false)
        expect(logic.values.generationPhase).toBeNull()

        logic.actions.setAgentTurn('run-1', true)
        expect(logic.values.isGenerating).toBe(true)
    })
})
