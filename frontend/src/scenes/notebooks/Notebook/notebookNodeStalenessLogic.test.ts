import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { JSONContent } from 'lib/components/RichContentEditor/types'

import { initKeaTests } from '~/test/init'

import { notebookNodeSQLV2Logic } from '../Nodes/notebookNodeSQLV2Logic'
import { NotebookNodeType } from '../types'
import { notebookNodeStalenessLogic } from './notebookNodeStalenessLogic'

describe('notebookNodeStalenessLogic', () => {
    // A three-cell chain plus one independent cell: sql cell `a` exports sql_df, python cell
    // `b` reads it and exports new_events, sql cell `c` joins new_events, and `x` references
    // nothing. Document order is dependency order.
    const content: JSONContent = {
        type: 'doc',
        content: [
            { type: NotebookNodeType.SQLV2, attrs: { nodeId: 'a', returnVariable: 'sql_df', code: 'select 1' } },
            {
                type: NotebookNodeType.PythonV2,
                attrs: { nodeId: 'b', returnVariable: 'new_events', code: 'new_events = sql_df.head()' },
            },
            {
                type: NotebookNodeType.SQLV2,
                attrs: { nodeId: 'c', returnVariable: 'joined', code: 'select * from new_events' },
            },
            { type: NotebookNodeType.SQLV2, attrs: { nodeId: 'x', returnVariable: 'other_df', code: 'select 2' } },
        ],
    }
    const getContent = (): JSONContent => content

    let stalenessLogic: ReturnType<typeof notebookNodeStalenessLogic.build>
    let nodeLogics: ReturnType<typeof notebookNodeSQLV2Logic.build>[]
    let runSpy: jest.SpyInstance
    let resultSpy: jest.SpyInstance

    const mountNode = (nodeId: string): ReturnType<typeof notebookNodeSQLV2Logic.build> => {
        const logic = notebookNodeSQLV2Logic({
            nodeId,
            notebookShortId: 'nb1',
            updateAttributes: jest.fn(),
            getContent,
        })
        logic.mount()
        nodeLogics.push(logic)
        return logic
    }

    beforeEach(() => {
        initKeaTests()
        nodeLogics = []
        stalenessLogic = notebookNodeStalenessLogic({ shortId: 'nb1' })
        stalenessLogic.mount()
        // Each dispatched run gets its own run id (r1, r2, …); results resolve as done unless
        // a test overrides resultSpy.
        let runCounter = 0
        runSpy = jest.spyOn(api.notebooks, 'sqlV2Run').mockImplementation(() => {
            runCounter += 1
            return Promise.resolve({ run_id: `r${runCounter}` })
        })
        resultSpy = jest.spyOn(api.notebooks, 'sqlV2RunResult').mockResolvedValue({
            status: 'done',
            result: { columns: [], first_page: [], row_count: 0 },
            error: null,
        })
    })

    afterEach(() => {
        nodeLogics.forEach((logic) => logic.unmount())
        stalenessLogic?.unmount()
        jest.restoreAllMocks()
    })

    it('a finished run marks transitive downstream cells stale and clears the finished cell', async () => {
        mountNode('a')
        stalenessLogic.actions.markStaleNodeIds(['a'])
        stalenessLogic.actions.nodeRunFinished('a', 'done', content)
        await expectLogic(stalenessLogic).toFinishAllListeners()
        // b reads a directly; c reads b, so staleness must propagate transitively.
        expect(stalenessLogic.values.staleNodeIds).toEqual({ b: true, c: true })
        // The finished cell is remembered as the last run with its still-stale downstream,
        // which is what surfaces the "run downstream cells" button on it.
        expect(stalenessLogic.values.lastRunNodeId).toEqual('a')
        expect(stalenessLogic.values.lastRunStaleDownstreamNodeIds).toEqual(['b', 'c'])
    })

    it('a rooted chain runs only cells downstream of the root, leaving unrelated stale cells flagged', async () => {
        // The "run downstream cells" button must not run stale cells its run did not affect;
        // without the root scope, x would be re-run by a chain rooted at a.
        mountNode('b')
        mountNode('c')
        mountNode('x')
        stalenessLogic.actions.markStaleNodeIds(['b', 'c', 'x'])

        stalenessLogic.actions.runStaleChain(content, 'a')
        await expectLogic(stalenessLogic).toFinishAllListeners()

        expect(runSpy.mock.calls.map((call) => call[1].node_id)).toEqual(['b', 'c'])
        expect(stalenessLogic.values.staleNodeIds).toEqual({ x: true })
        expect(stalenessLogic.values.chainQueue).toEqual([])
    })

    it('runStaleChain runs stale cells in document order and clears them all', async () => {
        mountNode('a')
        mountNode('b')
        mountNode('c')
        stalenessLogic.actions.markStaleNodeIds(['b', 'c'])

        stalenessLogic.actions.runStaleChain(content)
        await expectLogic(stalenessLogic).toFinishAllListeners()

        expect(runSpy).toHaveBeenCalledTimes(2)
        // b (the python cell) must run before c (the sql cell that joins its output), and
        // each run must carry the node's own type and output name.
        expect(runSpy.mock.calls[0][1]).toMatchObject({
            node_id: 'b',
            node_type: 'python',
            output_name: 'new_events',
        })
        expect(runSpy.mock.calls[1][1]).toMatchObject({ node_id: 'c' })
        expect(stalenessLogic.values.staleNodeIds).toEqual({})
        expect(stalenessLogic.values.chainQueue).toEqual([])
    })

    it('a chain run picks up cells its own completion marked stale', async () => {
        // The queue must be rebuilt as the chain advances: a's run marks b and c stale, and
        // a snapshot taken at chain start would finish "successfully" while they stay flagged.
        mountNode('a')
        mountNode('b')
        mountNode('c')
        stalenessLogic.actions.markStaleNodeIds(['a'])

        stalenessLogic.actions.runStaleChain(content)
        await expectLogic(stalenessLogic).toFinishAllListeners()

        expect(runSpy.mock.calls.map((call) => call[1].node_id)).toEqual(['a', 'b', 'c'])
        expect(stalenessLogic.values.staleNodeIds).toEqual({})
        expect(stalenessLogic.values.chainQueue).toEqual([])
    })

    it('skips a stale cell with no mounted logic instead of wedging the chain', async () => {
        // A dispatch to an unmounted cell is picked up by nobody: without the mounted-cell
        // filter the queue would sit at ['c'] forever, blocking any further stale-cell run.
        mountNode('b')
        stalenessLogic.actions.markStaleNodeIds(['b', 'c'])

        stalenessLogic.actions.runStaleChain(content)
        await expectLogic(stalenessLogic).toFinishAllListeners()

        expect(runSpy.mock.calls.map((call) => call[1].node_id)).toEqual(['b'])
        expect(stalenessLogic.values.chainQueue).toEqual([])
        // The unmounted cell keeps its flag — it was never re-run.
        expect(stalenessLogic.values.staleNodeIds).toEqual({ c: true })
    })

    it('the chain stops when a cell does not finish successfully', async () => {
        mountNode('b')
        mountNode('c')
        stalenessLogic.actions.markStaleNodeIds(['b', 'c'])
        // The first chain link fails; running c anyway would join a frame that was never rebuilt.
        resultSpy.mockResolvedValue({ status: 'failed', result: null, error: 'boom' })

        stalenessLogic.actions.runStaleChain(content)
        await expectLogic(stalenessLogic).toFinishAllListeners()

        expect(runSpy).toHaveBeenCalledTimes(1)
        expect(stalenessLogic.values.chainQueue).toEqual([])
        // The failed cell stays stale so the user can see what still needs a successful run.
        expect(stalenessLogic.values.staleNodeIds).toEqual({ b: true, c: true })
    })

    it('a second runStaleChain while one is active is refused', async () => {
        mountNode('b')
        // Keep the first link running so the chain stays active.
        resultSpy.mockResolvedValue({ status: 'running', result: null, error: null })
        stalenessLogic.actions.markStaleNodeIds(['b'])

        stalenessLogic.actions.runStaleChain(content)
        await expectLogic(stalenessLogic).toFinishAllListeners()
        stalenessLogic.actions.runStaleChain(content)
        await expectLogic(stalenessLogic).toFinishAllListeners()

        expect(runSpy).toHaveBeenCalledTimes(1)
    })
})
