import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { CANVAS_ENTRY_PATH } from '../editing/blockLibrary/blockProject'
import { canvasEditLogic } from '../editing/canvasEditLogic'
import { canvasSceneLogic } from '../scene/canvasSceneLogic'
import { canvasSidePanelLogic } from '../sidePanel/canvasSidePanelLogic'
import { canvasNewLogic } from './canvasNewLogic'

const CANVAS_ID = 'canvas-new-1'
const PROMPT = 'A chart of daily signups'

describe('canvasNewLogic', () => {
    let createdCanvas: Record<string, unknown> | null = null
    let createCount = 0
    let taskStatus = 201
    let linkStatus = 200
    let runCount = 0
    let publishStatus = 201
    let published: { project: { files: Record<string, string> }; expected_current_version_id: string | null } | null =
        null

    beforeEach(() => {
        createdCanvas = null
        createCount = 0
        linkStatus = 200
        runCount = 0
        published = null
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [
                    { id: 'space-me', name: 'me', system_role: 'personal' },
                    { id: 'space-growth', name: 'growth', system_role: null },
                ],
                '/api/projects/:team_id/canvases/:id/view/': () => [
                    200,
                    {
                        canvas: createdCanvas,
                        published_build: null,
                        current_version_id: null,
                        has_active_build: false,
                        source: null,
                        layout: null,
                        sandbox_document_url: null,
                    },
                ],
                '/api/projects/:team_id/tasks/:id/': { id: 'task-1', title: 'Daily signups', latest_run: null },
                '/api/projects/:team_id/canvases/:id/builds/': { builds: [], published_build_id: null },
                '/api/projects/:team_id/task_channels/:id/': { id: 'space-growth', name: 'growth', system_role: null },
                '/api/projects/:team_id/canvases/:id/source/': () => [
                    200,
                    {
                        canvas: createdCanvas,
                        project: {
                            schemaVersion: 1,
                            entryHtml: 'index.html',
                            files: { 'index.html': '<div id="root"></div>', [CANVAS_ENTRY_PATH]: '' },
                            dependencies: { react: '19.0.0' },
                            canvasSdkVersion: '0.2.0',
                        },
                        current_version_id: null,
                    },
                ],
            },
            post: {
                '/api/projects/:team_id/tasks/:id/run/': async ({ request }) => {
                    expect(await request.json()).toMatchObject({ run_source: 'manual' })
                    runCount++
                    return [201, { id: 'task-1', title: 'Daily signups', latest_run: { status: 'queued' } }]
                },
                '/api/projects/:team_id/canvases/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, string>
                    createCount += 1
                    createdCanvas = {
                        id: CANVAS_ID,
                        name: body.name,
                        kind: 'freeform',
                        channel: body.channel_id,
                        template_id: body.template_id,
                        generation_task_id: null,
                        published_build_id: null,
                    }
                    return [201, createdCanvas]
                },
                '/api/projects/:team_id/tasks/': async ({ request }) => {
                    expect(await request.json()).toMatchObject({ start_run: false })
                    return taskStatus === 201
                        ? [201, { id: 'task-1', title: 'Daily signups', latest_run: null }]
                        : [403, { error: 'Agent-started task runs are not available for this project' }]
                },
                '/api/projects/:team_id/canvases/:id/publish/': async ({ request }) => {
                    published = (await request.json()) as typeof published
                    return publishStatus === 201
                        ? [201, { current_version_id: 'version-1' }]
                        : [400, { detail: 'Invalid project' }]
                },
            },
            patch: {
                '/api/projects/:team_id/canvases/:id/': async ({ request }) => {
                    if (linkStatus !== 200) {
                        return [linkStatus, { detail: 'Link failed' }]
                    }

                    createdCanvas = { ...createdCanvas, ...((await request.json()) as Record<string, unknown>) }
                    return [200, createdCanvas]
                },
            },
        })
        initKeaTests()
    })

    test.each([
        ['the build starts', 201, 200, ''],
        ['the build fails to start', 403, 200, PROMPT],
        ['the task link fails', 201, 503, PROMPT],
    ])(
        'creates the canvas only on send and replaces the start page with it when %s',
        async (_, status, patchStatus, composerText) => {
            taskStatus = status
            linkStatus = patchStatus
            const logic = canvasNewLogic()
            logic.mount()
            router.actions.push(urls.canvasNew('space-growth'))
            await expectLogic(logic).toDispatchActions(['loadSpacesSuccess'])
            expect(logic.values.selectedSpaceId).toEqual('space-growth')
            expect(createdCanvas).toBeNull()

            logic.actions.setInstruction(PROMPT, false)
            logic.actions.send()
            logic.actions.send()
            await expectLogic(logic).toDispatchActions(['sendFinished'])

            expect(runCount).toBe(composerText ? 0 : 1)
            expect(createCount).toEqual(1)
            expect(createdCanvas).toMatchObject({ id: CANVAS_ID, channel: 'space-growth' })
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.canvasDetail(CANVAS_ID))
            expect(router.values.lastMethod).toEqual('REPLACE')

            const sceneLogic = canvasSceneLogic({ id: CANVAS_ID })
            sceneLogic.mount()
            await expectLogic(sceneLogic).toDispatchActions(['loadViewSuccess', 'loadSpaceSuccess'])
            expect(sceneLogic.values.instruction).toEqual(composerText)
            expect(logic.values.startHandoff).toBeNull()
        }
    )

    test.each([
        ['publishes the blank starter and opens it in edit mode on the Blocks tab', 201, true],
        ['lands on the empty canvas when the starter fails to publish', 400, false],
    ])('Start blank %s', async (_, status, editing) => {
        publishStatus = status
        const logic = canvasNewLogic()
        logic.mount()
        router.actions.push(urls.canvasNew('space-growth'))
        await expectLogic(logic).toDispatchActions(['loadSpacesSuccess'])

        logic.actions.startBlank()
        logic.actions.startBlank()
        logic.actions.send()
        await expectLogic(logic).toDispatchActions(['startBlankFinished'])

        expect(createCount).toEqual(1)
        expect(createdCanvas).toMatchObject({ id: CANVAS_ID, channel: 'space-growth' })
        expect(published?.expected_current_version_id).toBeNull()
        expect(published?.project.files[CANVAS_ENTRY_PATH]).toContain('<DateRange blockId="b-range" />')
        expect(Object.keys(published?.project.files ?? {})).toEqual(
            expect.arrayContaining(['src/blocks/runtime.tsx', 'src/blocks/DateRange.tsx', 'src/blocks/library.json'])
        )
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(urls.canvasDetail(CANVAS_ID))
        expect(router.values.lastMethod).toEqual('REPLACE')

        canvasSceneLogic({ id: CANVAS_ID }).mount()
        const editLogic = canvasEditLogic({ id: CANVAS_ID })
        editLogic.mount()
        expect(editLogic.values.editing).toBe(editing)
        expect(logic.values.editHandoff).toBeNull()
        if (editing) {
            expect(canvasSidePanelLogic.values).toMatchObject({ selectedTab: 'canvas-blocks', sidePanelOpen: true })
        }
    })
})
