import { MOCK_TEAM_ID } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import * as canvasApi from 'products/canvas/frontend/generated/api'
import type {
    CanvasApi,
    CanvasBuildsResponseApi,
    CanvasSourcePublishResponseApi,
    CanvasSourceResponseApi,
} from 'products/canvas/frontend/generated/api.schemas'
import * as tasksApi from 'products/tasks/frontend/generated/api'
import type { TaskDetailDTOApi } from 'products/tasks/frontend/generated/api.schemas'
import { TaskExecutionModeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { notebookNodeCanvasLogic } from './notebookNodeCanvasLogic'

const canvas: CanvasApi = {
    id: 'canvas-1',
    name: 'Make a spinning 3D globe',
    channel: 'channel-me',
    template_id: 'freeform',
    context: '',
    generation_task_id: null,
    pinned: false,
    pinned_at: null,
    current_version_id: null,
    published_build_id: null,
    created_by: {
        id: 1,
        uuid: 'user-1',
        email: 'canvas@example.com',
        hedgehog_config: null,
    },
    created_at: '2026-08-11T12:00:00Z',
    updated_at: '2026-08-11T12:00:00Z',
}

const task = { id: 'task-1' } as TaskDetailDTOApi
const source: CanvasSourceResponseApi = {
    canvas: {
        id: canvas.id,
        name: canvas.name,
        channel_id: canvas.channel,
        current_version_id: 'version-1',
        published_build_id: null,
        created_at: canvas.created_at,
    },
    project: {
        schemaVersion: 1,
        files: { 'src/canvas.tsx': 'export default function Canvas() { return null }' },
        entryHtml: 'index.html',
    },
    current_version_id: 'version-1',
}
const publishResult: CanvasSourcePublishResponseApi = {
    canvas: { ...source.canvas, current_version_id: 'version-2' },
    current_version_id: 'version-2',
    diagnostics: [],
}

describe('notebookNodeCanvasLogic', () => {
    let logic: ReturnType<typeof notebookNodeCanvasLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.mocked(posthog.captureException).mockClear()
        jest.spyOn(tasksApi, 'taskChannelsList').mockResolvedValue([
            {
                id: 'channel-me',
                name: 'me',
                channel_type: 'personal',
                github_integration: null,
                repositories: [],
                created_at: '2026-08-11T12:00:00Z',
            },
        ])
        jest.spyOn(canvasApi, 'canvasesCreate').mockResolvedValue(canvas)
        jest.spyOn(canvasApi, 'canvasesRetrieve').mockResolvedValue(canvas)
        jest.spyOn(canvasApi, 'canvasesBuildsRetrieve').mockResolvedValue({
            published_build_id: null,
            current_version_id: null,
            builds: [],
        })
        jest.spyOn(canvasApi, 'canvasesPartialUpdate').mockResolvedValue({
            ...canvas,
            generation_task_id: task.id,
        })
        jest.spyOn(canvasApi, 'canvasesSourceRetrieve').mockResolvedValue(source)
        jest.spyOn(tasksApi, 'tasksCreate').mockResolvedValue(task)
        jest.spyOn(tasksApi, 'tasksRetrieve').mockResolvedValue(task)
        jest.spyOn(tasksApi, 'tasksRunCreate').mockResolvedValue(task)
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('waits for an explicit action before creating a canvas from a prompt', async () => {
        const updateAttributes = jest.fn()
        const prompt = 'Make a spinning 3D globe showing signups by country'
        logic = notebookNodeCanvasLogic({
            id: '',
            nodeId: 'node-1',
            prompt,
            isEditable: true,
            updateAttributes,
        })
        logic.mount()

        await Promise.resolve()

        expect(canvasApi.canvasesCreate).not.toHaveBeenCalled()
        expect(tasksApi.tasksCreate).not.toHaveBeenCalled()
        expect(tasksApi.tasksRunCreate).not.toHaveBeenCalled()

        logic.actions.createFromPrompt()
        await waitFor(() => expect(tasksApi.tasksRunCreate).toHaveBeenCalledTimes(1))

        expect(tasksApi.taskChannelsList).toHaveBeenCalledWith(String(MOCK_TEAM_ID))
        expect(canvasApi.canvasesCreate).toHaveBeenCalledWith(String(MOCK_TEAM_ID), {
            name: prompt,
            channel_id: 'channel-me',
        })
        expect(updateAttributes).toHaveBeenCalledWith({ id: canvas.id, channelId: canvas.channel })
        expect(tasksApi.tasksCreate).toHaveBeenCalledWith(
            String(MOCK_TEAM_ID),
            expect.objectContaining({
                channel: canvas.channel,
                description: expect.stringContaining(prompt),
            })
        )
        expect(canvasApi.canvasesPartialUpdate).toHaveBeenCalledWith(String(MOCK_TEAM_ID), canvas.id, {
            context: prompt,
            generation_task_id: task.id,
        })
        expect(tasksApi.tasksRunCreate).toHaveBeenCalledWith(String(MOCK_TEAM_ID), task.id, {
            mode: TaskExecutionModeEnumApi.Background,
            pending_user_message: expect.stringContaining(canvas.id),
        })
        expect(logic.values.canvas?.generation_task_id).toBe(task.id)
        expect(canvasApi.canvasesCreate).toHaveBeenCalledTimes(1)
    })

    it('surfaces a failed generation task before the canvas has source', async () => {
        const failedCanvas = { ...canvas, generation_task_id: task.id }
        jest.mocked(canvasApi.canvasesRetrieve).mockResolvedValueOnce(failedCanvas)
        jest.mocked(tasksApi.tasksRetrieve).mockResolvedValueOnce({
            ...task,
            latest_run: {
                status: 'failed',
                error_message: 'SANDBOX_JWT_PRIVATE_KEY setting is required',
            },
        } as TaskDetailDTOApi)
        logic = notebookNodeCanvasLogic({
            id: canvas.id,
            nodeId: 'node-1',
            prompt: 'Make a spinning 3D globe',
            isEditable: true,
            updateAttributes: jest.fn(),
        })
        logic.mount()

        await waitFor(() =>
            expect(logic.values.generationError).toBe(
                "Couldn't build this canvas: SANDBOX_JWT_PRIVATE_KEY setting is required"
            )
        )

        expect(tasksApi.tasksRetrieve).toHaveBeenCalledWith(String(MOCK_TEAM_ID), task.id)
    })

    it('waits for an explicit action before updating a saved canvas from its prompt', async () => {
        const prompt = 'Add a weekly signups chart split by plan'
        logic = notebookNodeCanvasLogic({
            id: canvas.id,
            nodeId: 'node-1',
            prompt,
            isEditable: true,
            updateAttributes: jest.fn(),
        })
        logic.mount()

        await waitFor(() => expect(canvasApi.canvasesRetrieve).toHaveBeenCalledTimes(1))

        expect(canvasApi.canvasesCreate).not.toHaveBeenCalled()
        expect(tasksApi.tasksCreate).not.toHaveBeenCalled()
        expect(tasksApi.tasksRunCreate).not.toHaveBeenCalled()

        logic.actions.createFromPrompt()
        await waitFor(() => expect(tasksApi.tasksRunCreate).toHaveBeenCalledTimes(1))

        expect(canvasApi.canvasesCreate).not.toHaveBeenCalled()
        expect(tasksApi.tasksCreate).toHaveBeenCalledWith(
            String(MOCK_TEAM_ID),
            expect.objectContaining({
                channel: canvas.channel,
                description: expect.stringContaining(prompt),
            })
        )
        expect(canvasApi.canvasesPartialUpdate).toHaveBeenCalledWith(String(MOCK_TEAM_ID), canvas.id, {
            context: prompt,
            generation_task_id: task.id,
        })
    })

    it('does not create a prompt-only canvas without edit access', async () => {
        logic = notebookNodeCanvasLogic({
            id: '',
            nodeId: 'node-1',
            prompt: 'Make a spinning 3D globe',
            isEditable: false,
            updateAttributes: jest.fn(),
        })
        logic.mount()

        logic.actions.createFromPrompt()
        await Promise.resolve()

        expect(canvasApi.canvasesCreate).not.toHaveBeenCalled()
        expect(tasksApi.tasksCreate).not.toHaveBeenCalled()
        expect(logic.values.canvasCreationError).toBe('You need edit access to create this canvas.')
    })

    it('reports a failed prompt-only canvas creation', async () => {
        jest.mocked(tasksApi.taskChannelsList).mockResolvedValueOnce([])
        logic = notebookNodeCanvasLogic({
            id: '',
            nodeId: 'node-1',
            prompt: 'Make a spinning 3D globe',
            isEditable: true,
            updateAttributes: jest.fn(),
        })
        logic.mount()

        logic.actions.createFromPrompt()

        await waitFor(() =>
            expect(logic.values.canvasCreationError).toBe("Couldn't find a personal channel. Refresh and try again.")
        )
        expect(posthog.captureException).toHaveBeenCalledWith(expect.any(Error), {
            action: 'create notebook canvas from prompt',
        })
        expect(canvasApi.canvasesCreate).not.toHaveBeenCalled()
    })

    it('keeps an edit made while a source reload is in flight', async () => {
        let resolveSource: (value: CanvasSourceResponseApi) => void = () => {}
        jest.spyOn(canvasApi, 'canvasesSourceRetrieve').mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    resolveSource = resolve
                })
        )
        logic = notebookNodeCanvasLogic({
            id: canvas.id,
            nodeId: 'node-1',
            prompt: '',
            isEditable: true,
            updateAttributes: jest.fn(),
        })
        logic.mount()

        logic.actions.loadSource()
        logic.actions.setEditedCode('export default function NewerEdit() { return null }')
        resolveSource(source)

        await waitFor(() => expect(logic.values.source).toEqual(source))
        expect(logic.values.sourceCode).toBe('export default function NewerEdit() { return null }')

        logic.actions.discardSourceChanges()
        expect(logic.values.sourceCode).toBe(source.project.files['src/canvas.tsx'])
    })

    it('continues polling a published build after a transient request failure', async () => {
        jest.useFakeTimers()
        const readyBuilds = {
            published_build_id: 'build-1',
            current_version_id: publishResult.current_version_id,
            builds: [
                {
                    id: 'build-1',
                    source_version_id: publishResult.current_version_id,
                    build_status: 'ready',
                    diagnostics: [],
                    integrity: 'sha256',
                    artifact_url: 'https://example.com/canvas.html',
                    pinned: false,
                    created_at: '2026-08-11T12:00:00Z',
                    finished_at: '2026-08-11T12:00:01Z',
                },
            ],
        } as CanvasBuildsResponseApi
        jest.spyOn(canvasApi, 'canvasesBuildsRetrieve')
            .mockRejectedValueOnce(new Error('Temporary failure'))
            .mockResolvedValueOnce(readyBuilds)
        logic = notebookNodeCanvasLogic({
            id: '',
            nodeId: 'node-1',
            prompt: '',
            isEditable: true,
            updateAttributes: jest.fn(),
        })
        logic.mount()

        logic.actions.publishSourceSuccess(publishResult)
        await jest.advanceTimersByTimeAsync(4_000)

        expect(canvasApi.canvasesBuildsRetrieve).toHaveBeenCalledTimes(2)
        expect(logic.values.builds).toEqual(readyBuilds)
        expect(logic.values.isBuilding).toBe(false)
    })
})
