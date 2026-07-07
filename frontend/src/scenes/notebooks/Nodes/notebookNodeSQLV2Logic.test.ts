import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { NotebookNodeType } from '../types'
import { collectSqlV2Refs, notebookNodeSQLV2Logic } from './notebookNodeSQLV2Logic'

describe('notebookNodeSQLV2Logic', () => {
    let logic: ReturnType<typeof notebookNodeSQLV2Logic.build>
    let updateAttributes: jest.Mock
    let runSpy: jest.SpyInstance
    let resultSpy: jest.SpyInstance

    const mount = (props: Record<string, unknown> = {}): void => {
        logic = notebookNodeSQLV2Logic({ nodeId: 'n1', notebookShortId: 'nb1', updateAttributes, ...props })
        logic.mount()
    }

    beforeEach(() => {
        initKeaTests()
        updateAttributes = jest.fn()
        runSpy = jest.spyOn(api.notebooks, 'sqlV2Run').mockResolvedValue({ run_id: 'r1' })
        // Default: the run is still executing, so polling continues without resolving.
        resultSpy = jest
            .spyOn(api.notebooks, 'sqlV2RunResult')
            .mockResolvedValue({ status: 'running', result: null, error: null })
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    describe('collectSqlV2Refs', () => {
        const sqlNode = (nodeId: string, returnVariable: string): Record<string, unknown> => ({
            type: NotebookNodeType.SQLV2,
            attrs: { nodeId, returnVariable },
        })

        const doc = (...children: Record<string, unknown>[]): Record<string, unknown> => ({
            type: 'doc',
            content: children,
        })

        it('maps each named sibling to its node id, excluding the running node itself', () => {
            // Including self would inline the node as a CTE of its own name — a cycle the backend rejects.
            const document = doc(sqlNode('a', 'df1'), sqlNode('self', 'df2'), sqlNode('c', 'df3'))
            expect(collectSqlV2Refs(document, 'self')).toEqual({ df1: 'a', df3: 'c' })
        })

        it('skips nodes with a blank name', () => {
            const document = doc(sqlNode('a', ''), sqlNode('b', '  '))
            expect(collectSqlV2Refs(document, 'self')).toEqual({})
        })

        it('finds SQLV2 nodes nested inside other content', () => {
            const document = doc({ type: 'column', content: [sqlNode('a', 'df1')] })
            expect(collectSqlV2Refs(document, 'self')).toEqual({ df1: 'a' })
        })
    })

    it('rejects blank code before dispatching a run', async () => {
        mount()
        logic.actions.runQuery('   ')
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ runError: 'Query is empty — type some HogQL first.', isRunning: false })
        expect(runSpy).not.toHaveBeenCalled()
    })

    it('dispatches the run, persists the run id, and starts polling', async () => {
        mount()
        logic.actions.runQuery('select 1')
        await expectLogic(logic).toDispatchActions(['runQuery', 'startPolling', 'pollResult'])
        expect(runSpy).toHaveBeenCalledWith('nb1', { node_id: 'n1', code: 'select 1' })
        // The run id is persisted so a reload/remount can recover the in-flight run.
        expect(updateAttributes).toHaveBeenCalledWith({ runId: 'r1', result: null })
    })

    it('maps a done envelope into the node result and stops the spinner', async () => {
        resultSpy.mockResolvedValue({
            status: 'done',
            result: { columns: ['a'], first_page: [[1]], row_count: 1, has_more: false },
            error: null,
        })
        mount({ runId: 'r1', hasResult: false })
        await expectLogic(logic).toFinishAllListeners()
        expect(updateAttributes).toHaveBeenCalledWith({
            result: { columns: ['a'], types: [], row_count: 1, first_page: [[1]], has_more: false },
        })
        expect(logic.values.isRunning).toBe(false)
    })

    it('surfaces a failed run as an error', async () => {
        resultSpy.mockResolvedValue({ status: 'failed', result: null, error: 'no such table' })
        mount({ runId: 'r1', hasResult: false })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.runError).toBe('no such table')
        expect(logic.values.isRunning).toBe(false)
    })

    it('surfaces a run dispatch failure as an error', async () => {
        runSpy.mockRejectedValue(new Error('network down'))
        mount()
        logic.actions.runQuery('select 1')
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ runError: 'network down', isRunning: false })
    })

    it('resumes polling a persisted un-finished run on mount', async () => {
        mount({ runId: 'r1', hasResult: false })
        await expectLogic(logic).toDispatchActions(['startPolling', 'pollResult'])
        expect(resultSpy).toHaveBeenCalledWith('nb1', 'r1')
    })

    it('does not poll a persisted run that already has a result', async () => {
        mount({ runId: 'r1', hasResult: true })
        await expectLogic(logic).toFinishAllListeners()
        expect(resultSpy).not.toHaveBeenCalled()
    })

    it('a second sequential run replaces the first run result', async () => {
        resultSpy.mockImplementation((_s: string, runId: string) =>
            Promise.resolve(
                runId === 'r1'
                    ? { status: 'done', result: { columns: ['a'], first_page: [[1]], row_count: 1 }, error: null }
                    : { status: 'done', result: { columns: ['b'], first_page: [[2]], row_count: 1 }, error: null }
            )
        )
        mount()
        logic.actions.runQuery('select 1')
        await expectLogic(logic).toFinishAllListeners()
        runSpy.mockResolvedValueOnce({ run_id: 'r2' })
        logic.actions.runQuery('select 2')
        await expectLogic(logic).toFinishAllListeners()
        const resultWrites = updateAttributes.mock.calls.map((c) => c[0]).filter((a) => a.result)
        expect(resultWrites.at(-1).result).toEqual(expect.objectContaining({ columns: ['b'], first_page: [[2]] }))
    })

    it('ignores a stale poll from a previous run', async () => {
        // r1's poll stays in flight until we resolve it — after r2 has become the active run.
        let resolveR1: (value: unknown) => void = () => {}
        const r1Poll = new Promise((resolve) => {
            resolveR1 = resolve
        })
        resultSpy.mockImplementation((_shortId: string, runId: string) =>
            runId === 'r1' ? r1Poll : Promise.resolve({ status: 'running', result: null, error: null })
        )
        runSpy.mockResolvedValue({ run_id: 'r2' })

        // afterMount starts polling r1; wait until its poll is actually in flight.
        mount({ runId: 'r1', hasResult: false })
        await expectLogic(logic).toDispatchActions(['startPolling', 'pollResult'])

        // Start a new run while r1's poll is still pending — r2 becomes the active run.
        logic.actions.runQuery('select 2')
        await expectLogic(logic).toDispatchActions(['runQuery', 'startPolling'])

        // r1's stale poll now resolves with the OLD query's result.
        resolveR1({
            status: 'done',
            result: { columns: ['old'], first_page: [[1]], row_count: 1, has_more: false },
            error: null,
        })
        await expectLogic(logic).toFinishAllListeners()

        // The stale result must not overwrite the node, and r2's run must keep polling (not stopped).
        expect(updateAttributes).not.toHaveBeenCalledWith(
            expect.objectContaining({ result: expect.objectContaining({ columns: ['old'] }) })
        )
        expect(logic.values.isRunning).toBe(true)
    })

    it('blocks a second node while another node has a run in flight', async () => {
        // Default resultSpy keeps r1 'running', so the notebook stays busy after n1 dispatches.
        mount()
        const other = notebookNodeSQLV2Logic({ nodeId: 'n2', notebookShortId: 'nb1', updateAttributes })
        other.mount()
        logic.actions.runQuery('select 1')
        await expectLogic(logic).toFinishAllListeners()
        other.actions.runQuery('select 2')
        await expectLogic(other).toFinishAllListeners()
        expect(runSpy).toHaveBeenCalledTimes(1)
        expect(other.values.isRunning).toBe(false)
        expect(other.values.operationBlockReason).toBeTruthy()
        other.unmount()
    })

    it('blocks page fetches while another node is busy', async () => {
        const pageSpy = jest.spyOn(api.notebooks, 'sqlV2RunPage')
        mount()
        logic.actions.runQuery('select 1')
        await expectLogic(logic).toFinishAllListeners()
        const other = notebookNodeSQLV2Logic({
            nodeId: 'n2',
            notebookShortId: 'nb1',
            updateAttributes,
            runId: 'r9',
            hasResult: true,
        })
        other.mount()
        other.actions.setPage(2)
        await expectLogic(other).toFinishAllListeners()
        expect(pageSpy).not.toHaveBeenCalled()
        other.unmount()
    })

    it('releases the notebook when a run finishes so the next run can proceed', async () => {
        resultSpy.mockResolvedValue({
            status: 'done',
            result: { columns: ['a'], first_page: [[1]], row_count: 1 },
            error: null,
        })
        mount()
        const other = notebookNodeSQLV2Logic({ nodeId: 'n2', notebookShortId: 'nb1', updateAttributes })
        other.mount()
        logic.actions.runQuery('select 1')
        await expectLogic(logic).toFinishAllListeners()
        other.actions.runQuery('select 2')
        await expectLogic(other).toFinishAllListeners()
        expect(runSpy).toHaveBeenCalledTimes(2)
        other.unmount()
    })

    it('unmounting a busy node releases the notebook', async () => {
        mount()
        logic.actions.runQuery('select 1')
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()
        const other = notebookNodeSQLV2Logic({ nodeId: 'n2', notebookShortId: 'nb1', updateAttributes })
        other.mount()
        logic = other // afterEach unmounts this one; n1 is already unmounted
        other.actions.runQuery('select 2')
        await expectLogic(other).toFinishAllListeners()
        expect(runSpy).toHaveBeenCalledTimes(2)
    })
})
