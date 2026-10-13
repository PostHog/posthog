import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    notebooksRunsCreate,
    notebooksRunsInterruptCreate,
    notebooksRunsRetrieve,
} from 'products/notebooks/frontend/generated/api'

import { notebookLogic } from './notebookLogic'
import { notebookNodeStalenessLogic } from './notebookNodeStalenessLogic'
import { notebookOperationsLogic } from './notebookOperationsLogic'
import { notebookRunLogic } from './notebookRunLogic'

jest.mock('products/notebooks/frontend/generated/api', () => ({
    notebooksRunsCreate: jest.fn(),
    notebooksRunsRetrieve: jest.fn(),
    notebooksRunsInterruptCreate: jest.fn(),
}))

const SHORT_ID = 'nbrun01'

const cell = (node_id: string, status: string | null, run_id: string | null): any => ({
    node_id,
    cell_type: node_id === 'p1' ? 'python' : 'sql',
    dataframe_name: node_id,
    run_id,
    status,
    error: null,
})

const runStatus = (status: string, cells: any[], overrides: Record<string, unknown> = {}): any => ({
    run_id: 'nbrun-1',
    status,
    trigger: 'ui',
    variables: [],
    cell_count: cells.length,
    current_index: 0,
    current_node_id: cells[0]?.node_id ?? null,
    failed_node_id: null,
    error: null,
    cells,
    created_at: '2026-01-01T00:00:00Z',
    finished_at: null,
    ...overrides,
})

describe('notebookRunLogic', () => {
    let logic: ReturnType<typeof notebookRunLogic.build> | undefined

    beforeEach(() => {
        initKeaTests()
        jest.mocked(notebooksRunsCreate).mockResolvedValue({
            run_id: 'nbrun-1',
            cell_count: 2,
            starts_sandbox: false,
            sandbox_hourly_price: null,
        })
        jest.mocked(notebooksRunsInterruptCreate).mockResolvedValue({ interrupted: true, status: 'interrupted' })
    })

    afterEach(() => {
        logic?.unmount()
        logic = undefined
        jest.clearAllMocks()
    })

    it('hands each newly started cell to the cell that owns it', async () => {
        jest.mocked(notebooksRunsRetrieve).mockResolvedValueOnce(
            runStatus('running', [cell('s1', 'done', 'cell-1'), cell('p1', 'running', 'cell-2')])
        )
        logic = notebookRunLogic({ shortId: SHORT_ID })
        logic.mount()
        const staleness = notebookNodeStalenessLogic({ shortId: SHORT_ID })
        staleness.mount()

        await expectLogic(logic, () => logic!.actions.startRun())
            .toDispatchActions(['pollRun', 'setRun'])
            .toMatchValues({ progressLabel: 'Running cell 1 of 2' })
        // The started run's id is the only thing linking the poll to the run just created;
        // polling with undefined would 404 and silently abandon it.
        expect(notebooksRunsRetrieve).toHaveBeenCalledWith(expect.any(String), SHORT_ID, 'nbrun-1')
        await expectLogic(staleness).toDispatchActions([
            staleness.actionCreators.adoptChainRun('s1', 'cell-1'),
            staleness.actionCreators.adoptChainRun('p1', 'cell-2'),
        ])

        staleness.unmount()
    })

    it('holds the notebook busy while a run is active and releases it at the end', async () => {
        jest.mocked(notebooksRunsRetrieve).mockResolvedValueOnce(
            runStatus('running', [cell('s1', 'running', 'cell-1')])
        )
        logic = notebookRunLogic({ shortId: SHORT_ID })
        logic.mount()
        const operations = notebookOperationsLogic({ shortId: SHORT_ID })
        operations.mount()

        await expectLogic(logic, () => logic!.actions.startRun()).toDispatchActions(['setRun'])
        expect(operations.values.isBusy).toBe(true)

        jest.mocked(notebooksRunsRetrieve).mockResolvedValueOnce(runStatus('done', [cell('s1', 'done', 'cell-1')]))
        await expectLogic(logic, () => logic!.actions.pollRun()).toDispatchActions(['runFinished', 'stopPolling'])
        expect(operations.values.isBusy).toBe(false)

        operations.unmount()
    })

    it('rides out a transient status failure without dropping the run', async () => {
        // The backend keeps running whether or not one poll lands, so a blip must not leave
        // the UI stuck on Stop with the notebook held.
        jest.mocked(notebooksRunsRetrieve).mockResolvedValueOnce(
            runStatus('running', [cell('s1', 'running', 'cell-1')])
        )
        logic = notebookRunLogic({ shortId: SHORT_ID })
        logic.mount()
        const operations = notebookOperationsLogic({ shortId: SHORT_ID })
        operations.mount()
        await expectLogic(logic, () => logic!.actions.startRun()).toDispatchActions(['setRun'])

        jest.mocked(notebooksRunsRetrieve).mockRejectedValueOnce(new Error('network blip'))
        await expectLogic(logic, () => logic!.actions.pollRun()).toFinishAllListeners()

        expect(logic.values.isRunning).toBe(true)
        expect(operations.values.isBusy).toBe(true)

        jest.mocked(notebooksRunsRetrieve).mockResolvedValueOnce(runStatus('done', [cell('s1', 'done', 'cell-1')]))
        await expectLogic(logic, () => logic!.actions.pollRun()).toDispatchActions(['runFinished'])
        expect(operations.values.isBusy).toBe(false)

        operations.unmount()
    })

    it('recovers after a long outage instead of stranding the run', async () => {
        // Giving up released the notebook while the backend run was still live, which let a
        // per-cell run start underneath it, and left the banner on Stop with no way back.
        jest.mocked(notebooksRunsRetrieve).mockResolvedValueOnce(
            runStatus('running', [cell('s1', 'running', 'cell-1')])
        )
        logic = notebookRunLogic({ shortId: SHORT_ID })
        logic.mount()
        const operations = notebookOperationsLogic({ shortId: SHORT_ID })
        operations.mount()
        await expectLogic(logic, () => logic!.actions.startRun()).toDispatchActions(['setRun'])

        for (let attempt = 0; attempt < 8; attempt++) {
            jest.mocked(notebooksRunsRetrieve).mockRejectedValueOnce(new Error('offline'))
            await expectLogic(logic, () => logic!.actions.pollRun()).toFinishAllListeners()
        }

        // Well past the point the UI says it lost contact, and it is still watching.
        expect(logic.values.isRunning).toBe(true)
        expect(operations.values.isBusy).toBe(true)

        jest.mocked(notebooksRunsRetrieve).mockResolvedValueOnce(runStatus('done', [cell('s1', 'done', 'cell-1')]))
        await expectLogic(logic, () => logic!.actions.pollRun()).toDispatchActions(['runFinished'])
        expect(operations.values.isBusy).toBe(false)

        operations.unmount()
    })

    it('sends a Stop pressed before the run id arrives', async () => {
        // isStarting already renders Stop, so the click is reachable. It used to return here
        // without sending anything and without clearing the in-flight flag, leaving both Stop
        // controls disabled until the run finished on its own.
        let releaseStart: (value: any) => void = () => {}
        jest.mocked(notebooksRunsCreate).mockReturnValueOnce(
            new Promise((resolve) => {
                releaseStart = resolve
            }) as any
        )
        jest.mocked(notebooksRunsRetrieve).mockResolvedValue(
            runStatus('interrupted', [cell('s1', 'interrupted', 'cell-1')])
        )
        logic = notebookRunLogic({ shortId: SHORT_ID })
        logic.mount()

        logic.actions.startRun()
        logic.actions.interruptRun()
        expect(notebooksRunsInterruptCreate).not.toHaveBeenCalled()
        expect(logic.values.isInterrupting).toBe(false)

        releaseStart({ run_id: 'nbrun-1', cell_count: 1, starts_sandbox: false, sandbox_hourly_price: null })
        await expectLogic(logic).toFinishAllListeners()

        expect(notebooksRunsInterruptCreate).toHaveBeenCalledWith(expect.any(String), SHORT_ID, 'nbrun-1')
    })

    it('starts the run with the edits autosave is still holding', async () => {
        // Content saves debounce for 400ms and variables for 500ms, so a click straight after
        // an edit froze the previously saved code and values, and the results then landed
        // under newer text the user could see.
        const pending = {
            values: {
                localContent: { type: 'doc' } as any,
                variables: [{ name: 'days_back', type: 'number', value: 7 }],
            },
            actions: {
                saveNotebookNow: jest.fn(() => {
                    pending.values.localContent = null as any
                }),
            },
        }
        jest.spyOn(notebookLogic, 'findMounted').mockReturnValue(pending as any)
        jest.mocked(notebooksRunsRetrieve).mockResolvedValue(runStatus('done', [cell('s1', 'done', 'cell-1')]))
        logic = notebookRunLogic({ shortId: SHORT_ID })
        logic.mount()

        await expectLogic(logic, () => logic!.actions.startRun()).toDispatchActions(['setRun'])

        expect(pending.actions.saveNotebookNow).toHaveBeenCalled()
        expect(jest.mocked(notebooksRunsCreate).mock.calls[0][2]).toEqual({
            variables: [{ name: 'days_back', type: 'number', value: 7 }],
        })
    })

    it('reports a failed run against the cell that stopped it', async () => {
        jest.mocked(notebooksRunsRetrieve).mockResolvedValueOnce(
            runStatus('failed', [cell('s1', 'failed', 'cell-1'), cell('p1', null, null)], {
                failed_node_id: 's1',
            })
        )
        logic = notebookRunLogic({ shortId: SHORT_ID })
        logic.mount()

        await expectLogic(logic, () => logic!.actions.startRun()).toDispatchActions(['runFinished'])
        expect(logic.values.isRunning).toBe(false)
    })

    it('stops the run through the interrupt endpoint', async () => {
        jest.mocked(notebooksRunsRetrieve).mockResolvedValueOnce(
            runStatus('running', [cell('s1', 'running', 'cell-1')])
        )
        logic = notebookRunLogic({ shortId: SHORT_ID })
        logic.mount()
        await expectLogic(logic, () => logic!.actions.startRun()).toDispatchActions(['setRun'])

        jest.mocked(notebooksRunsRetrieve).mockResolvedValueOnce(
            runStatus('interrupted', [cell('s1', 'interrupted', 'cell-1')])
        )
        await expectLogic(logic, () => logic!.actions.interruptRun()).toDispatchActions(['runFinished'])

        expect(notebooksRunsInterruptCreate).toHaveBeenCalledWith(expect.any(String), SHORT_ID, 'nbrun-1')
        expect(logic.values.isRunning).toBe(false)
    })
})
