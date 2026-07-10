import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { JSONContent } from 'lib/components/RichContentEditor/types'

import { initKeaTests } from '~/test/init'

import { notebookNodeSQLV2Logic } from '../Nodes/notebookNodeSQLV2Logic'
import { NotebookNodeType } from '../types'
import { notebookNodeStalenessLogic } from './notebookNodeStalenessLogic'

describe('notebookNodeStalenessLogic', () => {
    // A three-cell chain: sql cell `a` exports sql_df, python cell `b` reads it and exports
    // new_events, sql cell `c` joins new_events. Document order is dependency order.
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

    it('a run with autoRunDependents chains its stale dependents without a click (input widgets)', async () => {
        // Journey 11: a widget's assignment landing must refresh the cells that read the
        // variable, not just mark them stale behind a banner.
        const widgetContent: JSONContent = {
            type: 'doc',
            content: [
                { type: NotebookNodeType.InputV2, attrs: { nodeId: 'w', variable: 'date_from' } },
                {
                    type: NotebookNodeType.PythonV2,
                    attrs: { nodeId: 'p', returnVariable: 'filtered', code: 'filtered = raw[raw.d >= date_from]' },
                },
            ],
        }
        const widgetLogic = notebookNodeSQLV2Logic({
            nodeId: 'w',
            notebookShortId: 'nb1',
            updateAttributes: jest.fn(),
            getContent: () => widgetContent,
        })
        widgetLogic.mount()
        nodeLogics.push(widgetLogic)
        const dependentLogic = notebookNodeSQLV2Logic({
            nodeId: 'p',
            notebookShortId: 'nb1',
            updateAttributes: jest.fn(),
            getContent: () => widgetContent,
        })
        dependentLogic.mount()
        nodeLogics.push(dependentLogic)

        widgetLogic.actions.runQuery('date_from = "2026-07-01"', {}, { nodeType: 'python', autoRunDependents: true })
        await expectLogic(stalenessLogic).toFinishAllListeners()
        await expectLogic(dependentLogic).toFinishAllListeners()

        // First run is the assignment, second is the dependent cell, no banner click involved.
        expect(runSpy).toHaveBeenCalledTimes(2)
        expect(runSpy.mock.calls[1][1]).toMatchObject({ node_id: 'p', node_type: 'python' })
        expect(stalenessLogic.values.staleNodeIds).toEqual({})
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
