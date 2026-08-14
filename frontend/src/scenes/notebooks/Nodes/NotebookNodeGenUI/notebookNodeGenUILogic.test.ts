import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { notebookNodeStalenessLogic } from 'scenes/notebooks/Notebook/notebookNodeStalenessLogic'
import { NotebookNodeType } from 'scenes/notebooks/types'

import { initKeaTests } from '~/test/init'

import {
    notebooksGenuiEnsure,
    notebooksGenuiRegenerate,
    notebooksGenuiRetry,
    notebooksGenuiRun,
    notebooksGenuiStatus,
} from 'products/notebooks/frontend/generated/api'
import type { GenUIStatusApi } from 'products/notebooks/frontend/generated/api.schemas'

import { notebookNodeSQLV2Logic } from '../notebookNodeSQLV2Logic'
import { notebookNodeGenUILogic } from './notebookNodeGenUILogic'

jest.mock('products/notebooks/frontend/generated/api', () => ({
    notebooksGenuiEnsure: jest.fn(),
    notebooksGenuiFrame: jest.fn(),
    notebooksGenuiRegenerate: jest.fn(),
    notebooksGenuiRetry: jest.fn(),
    notebooksGenuiRun: jest.fn(),
    notebooksGenuiStatus: jest.fn(),
}))

const status = (
    lifecycleStatus: GenUIStatusApi['lifecycle_status'],
    inputStatus: GenUIStatusApi['input_states'][number]['input_status'] = 'ready'
): GenUIStatusApi => ({
    node_id: 'globe',
    lifecycle_status: lifecycleStatus,
    artifact_url: lifecycleStatus === 'ready' || lifecycleStatus === 'stale' ? 'https://example.com/globe.html' : null,
    frame_names: ['locations_df'],
    input_states: [{ name: 'locations_df', input_status: inputStatus, producer_node_id: 'source' }],
    can_run: lifecycleStatus === 'stale',
    can_regenerate: true,
    can_retry: lifecycleStatus === 'failed',
    created_at: '2026-08-13T10:00:00Z',
    updated_at: '2026-08-13T10:00:00Z',
})

describe('notebookNodeGenUILogic', () => {
    const content: JSONContent = {
        type: 'doc',
        content: [
            {
                type: NotebookNodeType.SQLV2,
                attrs: { nodeId: 'source', returnVariable: 'locations_df', code: 'select 1' },
            },
            { type: NotebookNodeType.GenUI, attrs: { nodeId: 'globe', inputs: 'locations_df' } },
        ],
    }
    const props = {
        notebookShortId: 'notebook-1',
        nodeId: 'globe',
        prompt: 'Render a globe',
        inputs: ['locations_df'],
        serializedInputs: 'locations_df',
        persistedInputs: 'locations_df',
        inputValidationError: null,
        isEditable: true,
        getContent: (): JSONContent => content,
        updateAttributes: jest.fn(),
    }
    let logic: ReturnType<typeof notebookNodeGenUILogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.mocked(notebooksGenuiEnsure).mockReset()
        jest.mocked(notebooksGenuiStatus).mockReset()
        jest.mocked(notebooksGenuiRun).mockReset()
        jest.mocked(notebooksGenuiRegenerate).mockReset()
        jest.mocked(notebooksGenuiRetry).mockReset()
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it.each(['awaiting_inputs', 'generating', 'building', 'ready', 'stale', 'failed'] as const)(
        'stores the %s server lifecycle state',
        async (lifecycleStatus) => {
            jest.mocked(notebooksGenuiEnsure).mockResolvedValue(status(lifecycleStatus))
            logic = notebookNodeGenUILogic(props)
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.status?.lifecycle_status).toBe(lifecycleStatus)
        }
    )

    it('does not duplicate an ensure request while the first request is in flight', async () => {
        let resolveEnsure: (value: GenUIStatusApi) => void = () => undefined
        jest.mocked(notebooksGenuiEnsure).mockReturnValue(
            new Promise((resolve) => {
                resolveEnsure = resolve
            })
        )
        logic = notebookNodeGenUILogic(props)
        logic.mount()
        logic.actions.ensureVisualization()

        expect(notebooksGenuiEnsure).toHaveBeenCalledTimes(1)
        expect(logic.values.mutationInFlight).toBe(true)
        resolveEnsure(status('ready'))
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.mutationInFlight).toBe(false)
    })

    it('persists inferred inputs before starting generation', async () => {
        const updateAttributes = jest.fn()
        logic = notebookNodeGenUILogic({
            ...props,
            persistedInputs: '',
            updateAttributes,
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(updateAttributes).toHaveBeenCalledWith({ inputs: 'locations_df' })
        expect(notebooksGenuiEnsure).not.toHaveBeenCalled()
    })

    it('loads status without starting generation for a viewer', async () => {
        jest.mocked(notebooksGenuiStatus).mockResolvedValue(status('ready'))
        logic = notebookNodeGenUILogic({ ...props, isEditable: false })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksGenuiStatus).toHaveBeenCalledWith(String(MOCK_TEAM_ID), 'notebook-1', 'globe')
        expect(notebooksGenuiEnsure).not.toHaveBeenCalled()
    })

    it('clears local staleness after the server confirms fresh data', async () => {
        const stalenessLogic = notebookNodeStalenessLogic({ shortId: props.notebookShortId })
        stalenessLogic.mount()
        stalenessLogic.actions.markStaleNodeIds([props.nodeId])
        jest.mocked(notebooksGenuiEnsure).mockResolvedValue(status('ready'))

        logic = notebookNodeGenUILogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(stalenessLogic.values.staleNodeIds).toEqual({})
        stalenessLogic.unmount()
    })

    it('keeps polling after a transient status error', async () => {
        jest.useFakeTimers()
        jest.mocked(notebooksGenuiStatus)
            .mockRejectedValueOnce(new Error('Temporary error'))
            .mockResolvedValueOnce(status('ready'))
        logic = notebookNodeGenUILogic({ ...props, prompt: '' })
        logic.mount()
        logic.actions.statusReceived(status('generating'))

        await jest.advanceTimersByTimeAsync(3000)
        await Promise.resolve()
        expect(logic.values.error).toBe('Temporary error')

        await jest.advanceTimersByTimeAsync(3000)
        await Promise.resolve()
        expect(logic.values.status?.lifecycle_status).toBe('ready')
        expect(notebooksGenuiStatus).toHaveBeenCalledTimes(2)
    })

    it('runs required dataframe cells before continuing generation', async () => {
        const stalenessLogic = notebookNodeStalenessLogic({ shortId: props.notebookShortId })
        stalenessLogic.mount()
        const sourceLogic = notebookNodeSQLV2Logic({
            nodeId: 'source',
            notebookShortId: props.notebookShortId,
            updateAttributes: jest.fn(),
            getContent: () => content,
        })
        sourceLogic.mount()
        jest.spyOn(api.notebooks, 'sqlV2Run').mockResolvedValue({ run_id: 'source-run' })
        jest.spyOn(api.notebooks, 'sqlV2RunResult').mockResolvedValue({
            status: 'done',
            result: { columns: ['value'], types: [['value', 'Int64']], first_page: [[1]], row_count: 1 },
            error: null,
        })
        jest.mocked(notebooksGenuiEnsure)
            .mockResolvedValueOnce(status('awaiting_inputs', 'never_run'))
            .mockResolvedValueOnce(status('generating'))

        logic = notebookNodeGenUILogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(api.notebooks.sqlV2Run).toHaveBeenCalledWith(
            props.notebookShortId,
            expect.objectContaining({
                node_id: 'source',
            })
        )
        expect(notebooksGenuiEnsure).toHaveBeenCalledTimes(2)
        expect(logic.values.isRefreshingInputs).toBe(false)
        expect(logic.values.status?.lifecycle_status).toBe('generating')

        sourceLogic.unmount()
        stalenessLogic.unmount()
    })
})
