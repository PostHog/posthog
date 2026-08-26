import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api'

import { initKeaTests } from '~/test/init'

import {
    notebooksGenuiCancel,
    notebooksGenuiGenerate,
    notebooksGenuiRevert,
    notebooksGenuiSaveSource,
    notebooksGenuiSource,
    notebooksGenuiStatus,
} from 'products/notebooks/frontend/generated/api'
import type { GenUIStatusApi, GenUIVersionApi } from 'products/notebooks/frontend/generated/api.schemas'

import { formatGenUIElapsed, notebookNodeGenUILogic } from './notebookNodeGenUILogic'

jest.mock('products/notebooks/frontend/generated/api', () => ({
    notebooksGenuiCancel: jest.fn(),
    notebooksGenuiFrame: jest.fn(),
    notebooksGenuiGenerate: jest.fn(),
    notebooksGenuiRevert: jest.fn(),
    notebooksGenuiSaveSource: jest.fn(),
    notebooksGenuiSource: jest.fn(),
    notebooksGenuiStatus: jest.fn(),
}))

function status(lifecycleStatus: GenUIStatusApi['lifecycle_status']): GenUIStatusApi {
    return {
        lifecycle_status: lifecycleStatus,
        artifact_url: lifecycleStatus === 'ready' ? 'https://example.com/globe.html' : null,
        error_detail: null,
        frame_names: ['locations_df'],
        generation_started_at: null,
        generation_id: null,
        current_version_id: null,
        versions: [],
    }
}

function version(number: number): GenUIVersionApi {
    return {
        id: `00000000-0000-0000-0000-00000000000${number}`,
        parent_version_id: number > 1 ? `00000000-0000-0000-0000-00000000000${number - 1}` : null,
        version: number,
        operation: number === 1 ? 'initial' : 'improve',
        prompt: number === 1 ? 'Render a globe' : 'Make it lighter',
        effective_prompt: number === 1 ? 'Render a globe' : 'Render a globe\n\nAdditional change:\nMake it lighter',
        model: 'claude-sonnet-4-6',
        created_at: `2026-08-25T12:0${number}:00Z`,
        build_status: 'ready',
        artifact_url: `https://example.com/globe-${number}.html`,
    }
}

function versionedStatus(currentVersion: number, versions = [version(1), version(2)]): GenUIStatusApi {
    return {
        ...status('ready'),
        artifact_url: versions[currentVersion - 1].artifact_url,
        current_version_id: versions[currentVersion - 1].id,
        versions,
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
        jest.mocked(notebooksGenuiRevert).mockReset()
        jest.mocked(notebooksGenuiSaveSource).mockReset()
        jest.mocked(notebooksGenuiSource).mockReset()
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

        logic.actions.generateVisualization('Render a constellation', 'claude-sonnet-4-6', 'initial')
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksGenuiGenerate).toHaveBeenCalledWith(
            String(MOCK_TEAM_ID),
            'notebook-1',
            'globe',
            {
                prompt: 'Render a constellation',
                generation_id: expect.any(String),
                model: 'claude-sonnet-4-6',
                operation: 'initial',
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

        logic.actions.generateVisualization('Render a globe', 'claude-sonnet-4-6', 'initial')
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

        logic.actions.generateVisualization('Render a globe', 'claude-sonnet-4-6', 'initial')
        logic.actions.generateVisualization('Render a globe', 'claude-sonnet-4-6', 'initial')
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

        logic.actions.generateVisualization('Render a globe', 'claude-sonnet-4-6', 'initial')
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

        logic.actions.generateVisualization('Render a globe', 'claude-sonnet-4-6', 'initial')
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

        expect(logic.values.workingStatus).toMatchObject({
            detail: 'The source is ready. Building the interactive preview.',
            label: 'Building visualization…',
            timing: 'The preview build usually takes less than a minute.',
        })

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

    it('shows elapsed generation time as minutes and seconds', async () => {
        jest.useFakeTimers()
        let resolveGeneration: (value: GenUIStatusApi) => void = () => undefined
        jest.mocked(notebooksGenuiStatus).mockResolvedValue(status('awaiting_generation'))
        jest.mocked(notebooksGenuiGenerate).mockReturnValue(
            new Promise((resolve) => {
                resolveGeneration = resolve
            })
        )
        logic = notebookNodeGenUILogic(props)
        logic.mount()
        await Promise.resolve()

        logic.actions.generateVisualization('Render a globe', 'claude-sonnet-4-6', 'initial')
        await jest.advanceTimersByTimeAsync(65_000)

        expect(logic.values.elapsedSeconds).toBe(65)
        expect(formatGenUIElapsed(logic.values.elapsedSeconds)).toBe('01:05')
        expect(logic.values.workingStatus).toMatchObject({
            detail: 'Claude Sonnet 4.6 is generating the visualization source.',
            isOverEstimate: false,
            timing: 'Typical: ~2 min · Estimated remaining: 00:55',
        })

        await jest.advanceTimersByTimeAsync(60_000)
        expect(logic.values.workingStatus).toMatchObject({
            isOverEstimate: true,
            timing: 'Typical: ~2 min · 00:05 longer than usual. The request is still active.',
        })

        resolveGeneration(status('ready'))
        await expectLogic(logic).toFinishAllListeners()
    })

    it('prefills regeneration with the complete selected prompt and starts improvements empty', async () => {
        jest.mocked(notebooksGenuiStatus).mockResolvedValue(versionedStatus(2))
        logic = notebookNodeGenUILogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openGenerationModal('regenerate')
        expect(logic.values.generationDraftPrompt).toBe('Render a globe\n\nAdditional change:\nMake it lighter')
        expect(logic.values.generationDraftModel).toBe('claude-sonnet-4-6')

        logic.actions.openGenerationModal('improve')
        expect(logic.values.generationDraftPrompt).toBe('')
    })

    it('restores a selected historical version', async () => {
        const initialStatus = versionedStatus(2)
        const restoredStatus = versionedStatus(1)
        jest.mocked(notebooksGenuiStatus).mockResolvedValue(initialStatus)
        jest.mocked(notebooksGenuiRevert).mockResolvedValue(restoredStatus)
        logic = notebookNodeGenUILogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.selectVersion(version(1).id)
        logic.actions.restoreSelectedVersion()
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksGenuiRevert).toHaveBeenCalledWith(String(MOCK_TEAM_ID), 'notebook-1', 'globe', {
            version_id: version(1).id,
            expected_current_version_id: version(2).id,
        })
        expect(logic.values.selectedVersionId).toBe(version(1).id)
    })

    it('loads and saves current source as a new version', async () => {
        const initialStatus = versionedStatus(2)
        const savedStatus = versionedStatus(3, [version(1), version(2), version(3)])
        jest.mocked(notebooksGenuiStatus).mockResolvedValue(initialStatus)
        jest.mocked(notebooksGenuiSource).mockResolvedValue({
            version_id: version(2).id,
            current_version_id: version(2).id,
            source: 'export default function Canvas() { return <div /> }',
        })
        jest.mocked(notebooksGenuiSaveSource).mockResolvedValue(savedStatus)
        logic = notebookNodeGenUILogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openSourceEditor()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setSourceDraft('export default function Canvas() { return <main /> }')
        logic.actions.setSourceNote('Use a semantic root')
        logic.actions.saveSource()
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksGenuiSaveSource).toHaveBeenCalledWith(String(MOCK_TEAM_ID), 'notebook-1', 'globe', {
            source: 'export default function Canvas() { return <main /> }',
            prompt: 'Use a semantic root',
            expected_current_version_id: version(2).id,
        })
        expect(logic.values.selectedVersionId).toBe(version(3).id)
    })
})
