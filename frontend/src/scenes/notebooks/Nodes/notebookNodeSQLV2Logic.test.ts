import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import { buildMarkdownNotebookContent, serializeMarkdownNotebookComponent } from '../Notebook/markdownNotebookV2'
import { notebookSettingsLogic } from '../Notebook/notebookSettingsLogic'
import { NotebookNodeType } from '../types'
import {
    collectSqlV2Refs,
    notebookNodeSQLV2Logic,
    pollIntervalMs,
    sqlV2RunErrorMessage,
} from './notebookNodeSQLV2Logic'

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

    describe('sqlV2RunErrorMessage', () => {
        // The browser endpoints render every 404 as DRF's generic {"detail": "Not found."}, so the
        // message must come from the caller's notFoundKind, not from matching the backend string.
        const notFound = new ApiError(undefined, 404, undefined, { detail: 'Not found.' })

        it('names the notebook for a 404 on a notebook-addressed request', () => {
            expect(sqlV2RunErrorMessage(notFound, 'fallback', 'notebook')).toBe(
                'This notebook could not be found. It may have been deleted.'
            )
        })

        it('points at a rerun for a 404 on a result-addressed request', () => {
            // The result/page call sites rely on the default kind.
            expect(sqlV2RunErrorMessage(notFound, 'fallback')).toBe(
                'This query result is no longer available. Run the cell again.'
            )
        })

        it('keeps the original message for non-404 failures', () => {
            // A syntax error carries the detail the user needs; the not-found mapping must not swallow it.
            expect(sqlV2RunErrorMessage(new ApiError('Unexpected token', 400), 'fallback')).toBe('Unexpected token')
        })
    })

    describe('collectSqlV2Refs', () => {
        const sqlNode = (nodeId: string, returnVariable: string): JSONContent => ({
            type: NotebookNodeType.SQLV2,
            attrs: { nodeId, returnVariable },
        })

        const pythonNode = (nodeId: string, returnVariable?: string): JSONContent => ({
            type: NotebookNodeType.PythonV2,
            attrs: { nodeId, returnVariable },
        })

        const doc = (...children: JSONContent[]): JSONContent => ({
            type: 'doc',
            content: children,
        })

        const hogql = (node_id: string): { node_id: string; kind: 'hogql' } => ({ node_id, kind: 'hogql' })
        const local = (node_id: string): { node_id: string; kind: 'local' } => ({ node_id, kind: 'local' })

        it('maps each named sibling to its node id, excluding the running node itself', () => {
            // Including self would inline the node as a CTE of its own name — a cycle the backend rejects.
            const document = doc(sqlNode('a', 'df1'), sqlNode('self', 'df2'), sqlNode('c', 'df3'))
            expect(collectSqlV2Refs(document, 'self')).toEqual({ df1: hogql('a'), df3: hogql('c') })
        })

        it('disambiguates duplicate names the way the dependency graph does', () => {
            // Raw attributes would let node b shadow node a under the shared name —
            // the join would silently run against the wrong node's data.
            const document = doc(sqlNode('a', 'sql_df'), sqlNode('b', 'sql_df'), sqlNode('self', 'sql_df'))
            expect(collectSqlV2Refs(document, 'self')).toEqual({ sql_df: hogql('a'), sql_df_2: hogql('b') })
        })

        it('skips unnamed cells and lets a named sibling keep the default name', () => {
            // The dataframe name is optional: a blank-name cell is display-only and exports
            // nothing — and it must not push a real 'sql_df' cell into a disambiguated name.
            const document = doc(sqlNode('a', ''), sqlNode('b', '  '), sqlNode('c', 'sql_df'))
            expect(collectSqlV2Refs(document, 'self')).toEqual({ sql_df: hogql('c') })
        })

        it('skips cells with an invalid (non-identifier) name', () => {
            // `people-df` can never be referenced as a bare table name, so it must not be
            // offered as a ref that a downstream cell would fail to resolve.
            const document = doc(sqlNode('a', 'people-df'), sqlNode('b', 'good_df'))
            expect(collectSqlV2Refs(document, 'self')).toEqual({ good_df: hogql('b') })
        })

        it('finds SQLV2 nodes nested inside other content', () => {
            const document = doc({ type: 'column', content: [sqlNode('a', 'df1')] })
            expect(collectSqlV2Refs(document, 'self')).toEqual({ df1: hogql('a') })
        })

        it('collects python cells as local refs under their kernel variable name', () => {
            // Journey 5: a SQL node referencing new_events must reroute to DuckDB, which only
            // happens if the python cell's returnVariable reaches the backend as a local ref.
            // A blank name binds nothing in the kernel, so it exports no ref — otherwise every
            // unnamed cell would claim the same name and shadow the others. Only a cell with no
            // attribute at all predates the optional name and keeps the legacy 'df'.
            const document = doc(
                sqlNode('a', 'df1'),
                pythonNode('py', 'new_events'),
                pythonNode('py2', ''),
                pythonNode('py3')
            )
            expect(collectSqlV2Refs(document, 'self')).toEqual({
                df1: hogql('a'),
                new_events: local('py'),
                df: local('py3'),
            })
        })

        it('a sql ref wins a name collision with a python cell', () => {
            // SQL names are disambiguated in the UI; kernel variables are not — renaming the
            // local ref would break its correspondence with the kernel namespace, so it drops.
            const document = doc(sqlNode('a', 'df1'), pythonNode('py', 'df1'))
            expect(collectSqlV2Refs(document, 'self')).toEqual({ df1: hogql('a') })
        })

        it('collects refs from markdown notebook cells, preferring their persisted nodeId', () => {
            // Markdown notebooks (the only surface with SQLV2 cells) hold cells as tags inside
            // one markdown attribute — a tiptap-only walk returns {} and every ref breaks with
            // "Unknown table". Persisted nodeIds must win over parsed ids: parsed block ids are
            // content fingerprints that drift from the run's recorded node_id on any prop change.
            const markdown = [
                serializeMarkdownNotebookComponent('SQLV2', { nodeId: 'a', returnVariable: 'df1', code: 'select 1' }),
                serializeMarkdownNotebookComponent('SQLV2', { nodeId: 'self', returnVariable: 'df2', code: '' }),
                serializeMarkdownNotebookComponent('SQLV2', { returnVariable: 'df3', code: 'select 3' }),
                serializeMarkdownNotebookComponent('PythonV2', {
                    nodeId: 'py',
                    returnVariable: 'new_events',
                    code: 'x = 1',
                }),
            ].join('\n\n')
            const refs = collectSqlV2Refs(buildMarkdownNotebookContent(markdown), 'self')
            expect(refs.df1).toEqual(hogql('a'))
            expect(refs.df2).toBeUndefined()
            // Without a persisted nodeId the cell falls back to its parsed fingerprint id.
            expect(refs.df3?.node_id).toMatch(/^mdn-/)
            expect(refs.new_events).toEqual(local('py'))
        })
    })

    describe('pollIntervalMs', () => {
        // The steps are ordered slowest first and the lookup takes the first match, so
        // reordering them silently returns one cadence for every wait. That changes how many
        // requests a long-running cell makes by several times over, and nothing else catches it.
        it.each([
            [0, 1_000],
            [29_999, 1_000],
            [30_000, 2_000],
            [119_999, 2_000],
            [120_000, 5_000],
            [20 * 60 * 1_000, 5_000],
        ])('waits %ims into a run, so it polls every %ims', (waitedMs, expected) => {
            expect(pollIntervalMs(waitedMs)).toEqual(expected)
        })
    })

    describe('execution lanes', () => {
        it('pages a direct run client-side from the rows the result poll returned', async () => {
            // The server page endpoint refuses hogql runs; losing the local slice would
            // strand every page beyond the envelope's first.
            const rows = Array.from({ length: 120 }, (_, index) => [index])
            resultSpy.mockResolvedValue({
                status: 'done',
                result: {
                    columns: ['a'],
                    types: [['a', 'Int64']],
                    row_count: 50,
                    first_page: rows.slice(0, 50),
                    has_more: true,
                },
                error: null,
                rows,
            })
            const pageSpy = jest.spyOn(api.notebooks, 'sqlV2RunPage')
            mount({ runId: 'r1', hasResult: false })
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.directRows?.rows).toHaveLength(120)

            logic.actions.setPage(3)
            await expectLogic(logic).toFinishAllListeners()
            expect(pageSpy).not.toHaveBeenCalled()
            expect(logic.values.pageResult).toEqual({
                columns: ['a'],
                types: [['a', 'Int64']],
                rows: rows.slice(100, 120),
                has_more: false,
            })
        })

        it('opens the kernel panel and notifies for a kernel-lane run, and not for a direct one', async () => {
            // Scenario B: a run that needs the sandbox must surface the provisioning wait;
            // a pure-SQL run must never pop the panel or toast (it needs no sandbox at all).
            const toastSpy = jest.spyOn(lemonToast, 'info')
            mount()
            logic.actions.runQuery('select 1')
            await expectLogic(logic).toFinishAllListeners()
            expect(notebookSettingsLogic.findMounted()?.values.showKernelInfo).toBe(false)
            expect(logic.values.pendingKernelStart).toBe(false)
            expect(toastSpy).not.toHaveBeenCalled()

            logic.actions.runQuery('select * from new_events', { new_events: { node_id: 'py', kind: 'local' } })
            await expectLogic(logic).toFinishAllListeners()
            expect(notebookSettingsLogic.findMounted()?.values.showKernelInfo).toBe(true)
            expect(logic.values.pendingKernelStart).toBe(true)
            expect(toastSpy).toHaveBeenCalledWith(expect.stringContaining('Starting a compute sandbox'))
        })
    })

    it('rejects blank code before dispatching a run', async () => {
        mount()
        logic.actions.runQuery('   ')
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ runError: 'Nothing to run — type some code first.', isRunning: false })
        expect(runSpy).not.toHaveBeenCalled()
    })

    it('dispatches the run, persists the run id, and starts polling', async () => {
        mount()
        logic.actions.runQuery('select 1')
        await expectLogic(logic).toDispatchActions(['runQuery', 'startPolling', 'pollResult'])
        expect(runSpy).toHaveBeenCalledWith('nb1', { node_id: 'n1', code: 'select 1', refs: {} })
        // runId is persisted so a reload/remount can recover the in-flight run; nodeId is
        // pinned so the markdown cell's fingerprint id can't drift away from the run's node_id.
        expect(updateAttributes).toHaveBeenCalledWith({ nodeId: 'n1', runId: 'r1', result: null, runStatus: null })
    })

    it('shows the notebook-gone message when the run dispatch 404s', async () => {
        // A deleted or inaccessible notebook 404s the dispatch as a generic "Not found."; the cell
        // must say the notebook is gone, not send the user into a rerun loop for a result that
        // never existed.
        runSpy.mockRejectedValue(new ApiError(undefined, 404, undefined, { detail: 'Not found.' }))
        mount()
        logic.actions.runQuery('select 1')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.runError).toBe('This notebook could not be found. It may have been deleted.')
        expect(logic.values.isRunning).toBe(false)
    })

    it('dispatches a run against the cell’s connection', async () => {
        // Without this the run reaches the backend with no connection and executes on ClickHouse,
        // which is what made warehouse queries fail with "Unknown table".
        mount()
        logic.actions.runQuery('select 1', {}, { connectionId: 'conn-1', sendRawQuery: true })
        await expectLogic(logic).toDispatchActions(['runQuery', 'startPolling'])
        expect(runSpy).toHaveBeenCalledWith(
            'nb1',
            expect.objectContaining({ connection_id: 'conn-1', send_raw_query: true })
        )
    })

    it('dispatches a python run with its node type and output name', async () => {
        mount()
        logic.actions.runQuery(
            'df.head()',
            { sql_df: { node_id: 'other', kind: 'hogql' } },
            { nodeType: 'python', outputName: 'df' }
        )
        await expectLogic(logic).toDispatchActions(['runQuery', 'startPolling'])
        expect(runSpy).toHaveBeenCalledWith('nb1', {
            node_id: 'n1',
            code: 'df.head()',
            refs: { sql_df: { node_id: 'other', kind: 'hogql' } },
            node_type: 'python',
            output_name: 'df',
        })
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
            result: {
                columns: ['a'],
                types: [],
                row_count: 1,
                first_page: [[1]],
                has_more: false,
                stdout: '',
                stderr: '',
                media: [],
            },
            runStatus: 'done',
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

    it('surfaces an interrupted run with its partial output', async () => {
        // Journey 9: a stopped cell must still show what it printed before the interrupt,
        // with a notice instead of polling forever or rendering a bare failure.
        resultSpy.mockResolvedValue({
            status: 'interrupted',
            result: { columns: [], first_page: [], row_count: 0, stdout: 'partial output' },
            error: 'Run interrupted.',
        })
        mount({ runId: 'r1', hasResult: false })
        await expectLogic(logic).toFinishAllListeners()
        // The outcome is persisted with the partial result: without it a reload can't tell this
        // apart from a completed run, since both leave a result behind.
        expect(updateAttributes).toHaveBeenCalledWith({
            result: expect.objectContaining({ stdout: 'partial output' }),
            runStatus: 'interrupted',
        })
        expect(logic.values.runError).toBe('Run interrupted.')
        expect(logic.values.isRunning).toBe(false)
        expect(logic.values.isInterrupting).toBe(false)
    })

    it('interruptRun posts the active run to the interrupt endpoint and stays pending', async () => {
        const interruptSpy = jest.spyOn(api.notebooks, 'sqlV2RunInterrupt').mockResolvedValue({ status: 'running' })
        mount({ runId: 'r1', hasResult: false })
        await expectLogic(logic).toDispatchActions(['startPolling'])
        logic.actions.interruptRun()
        await expectLogic(logic).toFinishAllListeners()
        expect(interruptSpy).toHaveBeenCalledWith('nb1', 'r1')
        // The terminal state arrives via the poll; until then the Cancel button stays pending.
        expect(logic.values.isInterrupting).toBe(true)
    })

    it('an interrupt that stopped nothing resets the cancel button for a retry', async () => {
        jest.spyOn(api.notebooks, 'sqlV2RunInterrupt').mockResolvedValue({
            status: 'running',
            detail: 'The run has not reached the kernel yet. Try again in a moment.',
        })
        mount({ runId: 'r1', hasResult: false })
        await expectLogic(logic).toDispatchActions(['startPolling'])
        logic.actions.interruptRun()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.isInterrupting).toBe(false)
        expect(logic.values.isRunning).toBe(true)
    })

    it('a failed interrupt request resets the cancel button', async () => {
        jest.spyOn(api.notebooks, 'sqlV2RunInterrupt').mockRejectedValue(new Error('network down'))
        mount({ runId: 'r1', hasResult: false })
        await expectLogic(logic).toDispatchActions(['startPolling'])
        logic.actions.interruptRun()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.isInterrupting).toBe(false)
        expect(logic.values.isRunning).toBe(true)
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

    it('gives up the poller at the wait budget without leaving a stray timer', async () => {
        // Reaching the 21-minute client budget stops polling synchronously, which disposes the
        // poll timer. The self-rescheduling callback must not arm a new one afterwards: an
        // untracked timer would survive unmount and re-fire the failure every interval, aborting
        // any run-all chain waiting on this cell until a reload.
        jest.useFakeTimers()
        try {
            mount({ runId: 'r1', hasResult: false })
            // Let the first (still-running) poll settle so its scheduled follow-up is what trips
            // the budget next.
            await jest.advanceTimersByTimeAsync(0)

            // Jump the accumulated wait to the budget edge; the next scheduled poll trips it.
            logic.cache.pollWaitedMs = 21 * 60 * 1000
            await jest.advanceTimersByTimeAsync(1000)

            expect(logic.values.runError).toContain('Stopped checking')
            // The poller is disposed and, crucially, not re-armed. A stray timer would re-enter
            // the budget branch every interval, which each time accumulates the wait again — so an
            // unchanged wait after advancing past several intervals proves nothing rescheduled.
            expect(logic.cache.disposables.registry.has('pollResult')).toBe(false)
            const waitedAfterGivingUp = logic.cache.pollWaitedMs
            await jest.advanceTimersByTimeAsync(15_000)
            expect(logic.cache.pollWaitedMs).toBe(waitedAfterGivingUp)
        } finally {
            jest.useRealTimers()
        }
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
