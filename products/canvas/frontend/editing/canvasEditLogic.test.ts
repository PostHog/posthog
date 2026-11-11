import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import type { CanvasSourcePublishResponseApi, CanvasSourceResponseApi } from '../generated/api.schemas'
import { canvasSceneLogic } from '../scene/canvasSceneLogic'
import { canvasEditLogic } from './canvasEditLogic'

const source = {
    project: { schemaVersion: 1, entryHtml: 'index.html', files: { 'src/canvas.tsx': '<main>Saved</main>' } },
    current_version_id: 'v1',
    canvas: { id: 'canvas' } as CanvasSourceResponseApi['canvas'],
} as CanvasSourceResponseApi

const published = (version: string): CanvasSourcePublishResponseApi =>
    ({ current_version_id: version }) as CanvasSourcePublishResponseApi

describe('canvasEditLogic saving', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/canvases/:id/view/': {
                    canvas: { id: 'canvas', channel: 'space', kind: 'freeform', generation_task_id: null },
                    current_version_id: 'v1',
                    published_build: null,
                    has_active_build: false,
                },
                '/api/projects/:team_id/canvases/:id/builds/': { builds: [], published_build_id: null },
                '/api/projects/:team_id/canvases/:id/versions/': { results: [], next: null },
                '/api/projects/:team_id/canvases/:id/drafts/': [],
                '/api/projects/:team_id/task_channels/:id/': { id: 'space', name: 'Space' },
            },
        })
        initKeaTests()
        jest.spyOn(api, 'canvasesSourceRetrieve').mockResolvedValue(source)
    })
    afterEach(() => {
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    test.each(['loading', 'failed'])('Done exits when source is %s and no edits exist', async (state) => {
        jest.mocked(api.canvasesSourceRetrieve).mockImplementation(() => new Promise(() => {}))
        const publish = jest.spyOn(api, 'canvasesPublishCreate')
        const logic = canvasEditLogic({ id: 'canvas' })
        await expectLogic(canvasSceneLogic({ id: 'canvas' }), () => {
            logic.mount()
        }).toDispatchActions(['loadViewSuccess', 'loadSpaceSuccess'])
        logic.actions.setEditing(true)
        if (state === 'failed') {
            logic.actions.sourceLoadFailed('Source is unavailable')
        }
        logic.actions.finishEditing()
        expect(logic.values.editing).toBe(false)
        expect(publish).not.toHaveBeenCalled()
    })

    test.each([409, 503])('Done keeps recovery controls open after save status %s', async (status) => {
        jest.spyOn(api, 'canvasesPublishCreate').mockRejectedValue({ status, data: { current_version_id: 'v2' } })
        const logic = canvasEditLogic({ id: 'canvas' })
        logic.mount()
        await expectLogic(logic, () => logic.actions.setEditing(true)).toDispatchActions(['sourceLoaded'])
        logic.actions.applyEdit({ 'src/canvas.tsx': '<main>Changed</main>' }, 'Edited text')
        await expectLogic(logic, () => logic.actions.finishEditing()).toDispatchActions([
            status === 409 ? 'conflictDetected' : 'saveFailed',
        ])
        expect(logic.values.editing).toBe(true)
        expect(logic.values.entry?.saving).toBe(false)
    })

    test('saves a later edit after the in-flight save completes following unmount', async () => {
        let complete!: (result: CanvasSourcePublishResponseApi) => void
        const publish = jest
            .spyOn(api, 'canvasesPublishCreate')
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        complete = resolve
                    })
            )
            .mockResolvedValue(published('v3'))
        const logic = canvasEditLogic({ id: 'canvas' })
        const unmount = logic.mount()
        logic.actions.sourceLoaded(source)
        logic.actions.applyEdit({ 'src/canvas.tsx': '<main>First</main>' }, 'First edit')
        logic.actions.save()
        logic.actions.applyEdit({ 'src/canvas.tsx': '<main>Second</main>' }, 'Second edit')
        unmount()
        complete(published('v2'))
        await Promise.resolve()
        await Promise.resolve()
        expect(publish).toHaveBeenLastCalledWith(
            expect.any(String),
            'canvas',
            expect.objectContaining({
                expected_current_version_id: 'v2',
                project: expect.objectContaining({ files: { 'src/canvas.tsx': '<main>Second</main>' } }),
            })
        )
        expect(publish).toHaveBeenCalledTimes(2)
    })

    test('autosaves while the document is hidden', async () => {
        const publish = jest.spyOn(api, 'canvasesPublishCreate').mockResolvedValue(published('v2'))
        const logic = canvasEditLogic({ id: 'canvas' })
        logic.mount()
        logic.actions.sourceLoaded(source)
        jest.useFakeTimers()
        logic.actions.applyEdit({ 'src/canvas.tsx': '<main>Changed</main>' }, 'Edited text')
        const hidden = jest.spyOn(document, 'hidden', 'get').mockReturnValue(true)
        document.dispatchEvent(new Event('visibilitychange'))
        await jest.advanceTimersByTimeAsync(700)
        expect(publish).toHaveBeenCalledTimes(1)
        hidden.mockRestore()
    })
})
