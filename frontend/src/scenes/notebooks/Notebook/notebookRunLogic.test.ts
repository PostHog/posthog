import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import * as notebooksApi from 'products/notebooks/frontend/generated/api'
import type { NotebookRunStatusResponseApi } from 'products/notebooks/frontend/generated/api.schemas'

import { notebookOperationsLogic } from './notebookOperationsLogic'
import { notebookRunLogic } from './notebookRunLogic'

const cell = (
    nodeId: string,
    overrides: Partial<NotebookRunStatusResponseApi['cells'][number]> = {}
): NotebookRunStatusResponseApi['cells'][number] => ({
    node_id: nodeId,
    cell_type: 'sql',
    dataframe_name: `${nodeId}_df`,
    run_id: null,
    status: null,
    error: null,
    ...overrides,
})

const runStatus = (overrides: Partial<NotebookRunStatusResponseApi> = {}): NotebookRunStatusResponseApi => ({
    run_id: 'nbrun-1',
    status: 'running',
    trigger: 'ui',
    variables: [],
    current_node_id: 'n1',
    current_index: 0,
    failed_node_id: null,
    error: null,
    cells: [cell('n1'), cell('n2')],
    created_at: '2026-01-01T00:00:00Z',
    finished_at: null,
    ...overrides,
})

describe('notebookRunLogic', () => {
    let logic: ReturnType<typeof notebookRunLogic.build>
    let createSpy: jest.SpyInstance
    let retrieveSpy: jest.SpyInstance
    let interruptSpy: jest.SpyInstance

    const mount = (): void => {
        logic = notebookRunLogic({ shortId: 'nb1' })
        logic.mount()
    }

    beforeEach(() => {
        initKeaTests()
        createSpy = jest.spyOn(notebooksApi, 'notebooksRunsCreate').mockResolvedValue({
            run_id: 'nbrun-1',
            cell_count: 2,
            starts_sandbox: false,
            sandbox_hourly_price: null,
        })
        retrieveSpy = jest.spyOn(notebooksApi, 'notebooksRunsRetrieve').mockResolvedValue(runStatus())
        interruptSpy = jest
            .spyOn(notebooksApi, 'notebooksRunsInterruptCreate')
            .mockResolvedValue({ interrupted: true, status: 'interrupted' })
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('starts a run, holds the notebook, and reports its progress', async () => {
        mount()
        logic.actions.startRun()

        await expectLogic(logic).toDispatchActions(['setStarted', 'setRun']).toMatchValues({
            runId: 'nbrun-1',
            cellCount: 2,
            isRunning: true,
            progressLabel: 'Running cell 1 of 2',
        })
        expect(createSpy).toHaveBeenCalled()
        // Every per-cell run button must say the notebook is busy while the run walks it.
        expect(notebookOperationsLogic({ shortId: 'nb1' }).values.isBusy).toBe(true)
    })

    it('hands each cell its run id so the cell writes the result itself', async () => {
        // The backend never edits the document; the cell logic that adopts the run does.
        retrieveSpy.mockResolvedValue(runStatus({ cells: [cell('n1', { run_id: 'r1', status: 'done' }), cell('n2')] }))
        mount()
        logic.actions.startRun()

        await expectLogic(logic).toDispatchActions([
            'setRun',
            (action) =>
                action.type === logic.actionTypes.adoptChainRun &&
                action.payload.nodeId === 'n1' &&
                action.payload.runId === 'r1',
        ])
    })

    it('discloses the sandbox price before a Python run provisions one', async () => {
        const toast = jest.spyOn(lemonToast, 'info')
        createSpy.mockResolvedValue({
            run_id: 'nbrun-1',
            cell_count: 2,
            starts_sandbox: true,
            sandbox_hourly_price: 0.42,
        })
        mount()
        logic.actions.startRun()

        await expectLogic(logic).toDispatchActions(['setStarted'])
        expect(toast).toHaveBeenCalledWith(expect.stringContaining('$0.42 / h'))
    })

    it('names the failed cell and releases the notebook when the run stops', async () => {
        const toast = jest.spyOn(lemonToast, 'error')
        retrieveSpy.mockResolvedValue(
            runStatus({
                status: 'failed',
                failed_node_id: 'n2',
                cells: [cell('n1', { run_id: 'r1', status: 'done' }), cell('n2', { run_id: 'r2', status: 'failed' })],
            })
        )
        mount()
        logic.actions.startRun()

        await expectLogic(logic).toDispatchActions(['runFinished']).toMatchValues({ isRunning: false })
        expect(toast).toHaveBeenCalledWith('n2_df failed, so the run stopped there.')
        expect(notebookOperationsLogic({ shortId: 'nb1' }).values.isBusy).toBe(false)
    })

    it('an interrupt reads the outcome back rather than assuming it landed', async () => {
        // The stop can lose the race to a run that just finished, and the toast must not claim
        // otherwise.
        mount()
        logic.actions.startRun()
        await expectLogic(logic).toDispatchActions(['setRun'])
        retrieveSpy.mockResolvedValue(runStatus({ status: 'done', current_node_id: null, finished_at: 'now' }))

        logic.actions.interruptRun()

        await expectLogic(logic).toDispatchActions(['interruptRun', 'runFinished']).toMatchValues({ isRunning: false })
        expect(interruptSpy).toHaveBeenCalledWith(expect.anything(), 'nb1', 'nbrun-1')
    })

    it('a refused start leaves the notebook free', async () => {
        const toast = jest.spyOn(lemonToast, 'error')
        createSpy.mockRejectedValue({ data: { detail: 'This notebook is already running.' } })
        mount()
        logic.actions.startRun()

        await expectLogic(logic).toDispatchActions(['stopTracking']).toMatchValues({ isRunning: false })
        expect(toast).toHaveBeenCalledWith('This notebook is already running.')
        expect(notebookOperationsLogic({ shortId: 'nb1' }).values.isBusy).toBe(false)
    })
})
