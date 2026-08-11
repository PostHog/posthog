import { MOCK_TEAM_ID } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import * as canvasApi from 'products/canvas/frontend/generated/api'
import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'
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

describe('notebookNodeCanvasLogic', () => {
    let logic: ReturnType<typeof notebookNodeCanvasLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(tasksApi, 'taskChannelsList').mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: [
                {
                    id: 'channel-me',
                    name: 'me',
                    channel_type: 'personal',
                    github_integration: null,
                    repositories: [],
                    created_at: '2026-08-11T12:00:00Z',
                },
            ],
        })
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
        jest.spyOn(tasksApi, 'tasksCreate').mockResolvedValue(task)
        jest.spyOn(tasksApi, 'tasksRunCreate').mockResolvedValue(task)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('creates one canvas from a prompt, persists its id, and starts its generation task', async () => {
        const updateAttributes = jest.fn()
        const prompt = 'Make a spinning 3D globe showing signups by country'
        logic = notebookNodeCanvasLogic({
            id: '',
            nodeId: 'node-1',
            prompt,
            updateAttributes,
        })
        logic.mount()

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
        expect(canvasApi.canvasesCreate).toHaveBeenCalledTimes(1)
    })

    it('does not regenerate a saved canvas when its node also keeps the original prompt', async () => {
        logic = notebookNodeCanvasLogic({
            id: canvas.id,
            nodeId: 'node-1',
            prompt: 'The original request',
            updateAttributes: jest.fn(),
        })
        logic.mount()

        await waitFor(() => expect(canvasApi.canvasesRetrieve).toHaveBeenCalledTimes(1))

        expect(canvasApi.canvasesCreate).not.toHaveBeenCalled()
        expect(tasksApi.tasksCreate).not.toHaveBeenCalled()
        expect(tasksApi.tasksRunCreate).not.toHaveBeenCalled()
    })
})
