import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { notebooksGenuiGenerate, notebooksGenuiStatus } from 'products/notebooks/frontend/generated/api'
import type { GenUIStatusApi } from 'products/notebooks/frontend/generated/api.schemas'

import { notebookNodeGenUILogic } from './notebookNodeGenUILogic'

jest.mock('products/notebooks/frontend/generated/api', () => ({
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

describe('notebookNodeGenUILogic', () => {
    const props = {
        notebookShortId: 'notebook-1',
        nodeId: 'globe',
        prompt: 'Render a globe',
        inputs: ['locations_df'],
        inputValidationError: null,
        isEditable: true,
    }
    let logic: ReturnType<typeof notebookNodeGenUILogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.mocked(notebooksGenuiGenerate).mockReset()
        jest.mocked(notebooksGenuiStatus).mockReset()
    })

    afterEach(() => {
        logic?.unmount()
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

    it('generates only after an explicit action', async () => {
        jest.mocked(notebooksGenuiStatus).mockResolvedValue(status('awaiting_generation'))
        jest.mocked(notebooksGenuiGenerate).mockResolvedValue(status('building'))
        logic = notebookNodeGenUILogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.generateVisualization()
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksGenuiGenerate).toHaveBeenCalledWith(String(MOCK_TEAM_ID), 'notebook-1', 'globe', {
            prompt: 'Render a globe',
            inputs: ['locations_df'],
        })
        expect(logic.values.status?.lifecycle_status).toBe('building')
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
