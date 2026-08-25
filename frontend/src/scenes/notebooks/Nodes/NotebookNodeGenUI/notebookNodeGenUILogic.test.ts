import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api'

import { initKeaTests } from '~/test/init'

import {
    notebooksGenuiCancel,
    notebooksGenuiGenerate,
    notebooksGenuiStatus,
} from 'products/notebooks/frontend/generated/api'
import type { GenUIStatusApi } from 'products/notebooks/frontend/generated/api.schemas'

import { notebookNodeGenUILogic } from './notebookNodeGenUILogic'

jest.mock('products/notebooks/frontend/generated/api', () => ({
    notebooksGenuiCancel: jest.fn(),
    notebooksGenuiFrame: jest.fn(),
    notebooksGenuiGenerate: jest.fn(),
    notebooksGenuiStatus: jest.fn(),
}))

function status(lifecycleStatus: GenUIStatusApi['lifecycle_status']): GenUIStatusApi {
    return {
        lifecycle_status: lifecycleStatus,
        artifact_url: lifecycleStatus === 'ready' ? 'https://example.com/globe.html' : null,
        error_detail: null,
        frame_names: ['locations_df'],
    }
}

function setDocumentHidden(hidden: boolean): void {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    Object.defineProperty(document, 'visibilityState', {
        configurable: true,
        get: () => (hidden ? 'hidden' : 'visible'),
    })
    document.dispatchEvent(new Event('visibilitychange'))
}

describe('notebookNodeGenUILogic', () => {
    const props = {
        notebookShortId: 'notebook-1',
        nodeId: 'globe',
        prompt: 'Render a globe',
        model: 'claude-sonnet-4-6' as const,
        isEditable: true,
        persistNotebook: jest.fn(async () => undefined),
    }
    let logic: ReturnType<typeof notebookNodeGenUILogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.mocked(notebooksGenuiCancel).mockReset()
        jest.mocked(notebooksGenuiGenerate).mockReset()
        jest.mocked(notebooksGenuiStatus).mockReset()
        props.persistNotebook.mockClear()
        setDocumentHidden(false)
    })

    afterEach(() => {
        logic?.unmount()
        setDocumentHidden(false)
        jest.useRealTimers()
    })

    it('loads status without generating on mount', async () => {
        jest.mocked(notebooksGenuiStatus).mockResolvedValue(status('awaiting_generation'))
        logic = notebookNodeGenUILogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksGenuiStatus).toHaveBeenCalledWith(String(MOCK_TEAM_ID), 'notebook-1', 'globe')
        expect(notebooksGenuiGenerate).not.toHaveBeenCalled()
    })

    it('waits for an explicit action after the prompt changes', async () => {
        jest.mocked(notebooksGenuiStatus).mockResolvedValue(status('awaiting_generation'))
        jest.mocked(notebooksGenuiGenerate).mockResolvedValue(status('building'))
        logic = notebookNodeGenUILogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        notebookNodeGenUILogic({ ...props, prompt: 'Render a constellation' })
        await Promise.resolve()

        expect(notebooksGenuiGenerate).not.toHaveBeenCalled()

        logic.actions.generateVisualization()
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksGenuiGenerate).toHaveBeenCalledWith(
            String(MOCK_TEAM_ID),
            'notebook-1',
            'globe',
            {
                prompt: 'Render a constellation',
                generation_id: expect.any(String),
                model: 'claude-sonnet-4-6',
            },
            { signal: expect.any(AbortSignal) }
        )
        expect(logic.values.status?.lifecycle_status).toBe('building')
    })

    it('cancels the active request and clears the loading state', async () => {
        jest.mocked(notebooksGenuiStatus).mockResolvedValue(status('awaiting_generation'))
        jest.mocked(notebooksGenuiCancel).mockResolvedValue(undefined)
        jest.mocked(notebooksGenuiGenerate).mockImplementation(
            (_projectId, _shortId, _nodeId, _request, options) =>
                new Promise((_resolve, reject) => {
                    options?.signal?.addEventListener('abort', () => reject(new DOMException('Canceled', 'AbortError')))
                })
        )
        logic = notebookNodeGenUILogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.generateVisualization()
        await Promise.resolve()
        const generationId = jest.mocked(notebooksGenuiGenerate).mock.calls[0][3].generation_id
        expect(logic.values.generationInFlight).toBe(true)

        logic.actions.cancelGeneration()
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksGenuiCancel).toHaveBeenCalledWith(String(MOCK_TEAM_ID), 'notebook-1', 'globe', {
            generation_id: generationId,
        })
        expect(logic.values.cancellationInFlight).toBe(false)
        expect(logic.values.generationInFlight).toBe(false)
        expect(logic.values.error).toBeNull()
    })

    it('deduplicates generation while the request is in flight', async () => {
        let resolveGeneration: (value: GenUIStatusApi) => void = () => undefined
        jest.mocked(notebooksGenuiStatus).mockResolvedValue(status('awaiting_generation'))
        jest.mocked(notebooksGenuiGenerate).mockReturnValue(
            new Promise((resolve) => {
                resolveGeneration = resolve
            })
        )
        logic = notebookNodeGenUILogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.generateVisualization()
        logic.actions.generateVisualization()
        expect(notebooksGenuiGenerate).toHaveBeenCalledTimes(1)

        resolveGeneration(status('ready'))
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.generationInFlight).toBe(false)
    })

    it('persists the notebook and retries when the generated node is missing from stored content', async () => {
        jest.mocked(notebooksGenuiStatus).mockResolvedValue(status('awaiting_generation'))
        jest.mocked(notebooksGenuiGenerate)
            .mockRejectedValueOnce(
                new ApiError('Not found', 404, undefined, {
                    code: 'node_not_found',
                    detail: 'This generated visualization is no longer in the notebook.',
                })
            )
            .mockResolvedValueOnce(status('building'))
        logic = notebookNodeGenUILogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.generateVisualization()
        await expectLogic(logic).toFinishAllListeners()

        expect(props.persistNotebook).toHaveBeenCalledTimes(1)
        expect(notebooksGenuiGenerate).toHaveBeenCalledTimes(2)
        expect(jest.mocked(notebooksGenuiGenerate).mock.calls[1][3]).toEqual(
            jest.mocked(notebooksGenuiGenerate).mock.calls[0][3]
        )
        expect(logic.values.status?.lifecycle_status).toBe('building')
        expect(logic.values.error).toBeNull()
    })

    it('keeps generating when the page is hidden', async () => {
        let resolveGeneration: (value: GenUIStatusApi) => void = () => undefined
        jest.mocked(notebooksGenuiStatus).mockResolvedValue(status('awaiting_generation'))
        jest.mocked(notebooksGenuiGenerate).mockReturnValue(
            new Promise((resolve) => {
                resolveGeneration = resolve
            })
        )
        logic = notebookNodeGenUILogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.generateVisualization()
        await Promise.resolve()
        const signal = jest.mocked(notebooksGenuiGenerate).mock.calls[0][4]?.signal

        setDocumentHidden(true)

        expect(signal?.aborted).toBe(false)
        expect(logic.values.generationInFlight).toBe(true)

        resolveGeneration(status('ready'))
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.generationInFlight).toBe(false)
    })

    it('polls only while the Canvas build is active', async () => {
        jest.useFakeTimers()
        jest.mocked(notebooksGenuiStatus)
            .mockResolvedValueOnce(status('building'))
            .mockResolvedValueOnce(status('ready'))
        logic = notebookNodeGenUILogic(props)
        logic.mount()
        await Promise.resolve()

        await jest.advanceTimersByTimeAsync(1_000)
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksGenuiStatus).toHaveBeenCalledTimes(2)
        expect(logic.values.status?.lifecycle_status).toBe('ready')
    })

    it('reloads data locally without another generation', async () => {
        jest.mocked(notebooksGenuiStatus).mockResolvedValue(status('ready'))
        logic = notebookNodeGenUILogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.refreshData()

        expect(logic.values.frameRevision).toBe(1)
        expect(notebooksGenuiGenerate).not.toHaveBeenCalled()
    })
})
