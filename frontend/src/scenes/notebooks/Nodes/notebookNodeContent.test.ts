import { NotebookNodeType } from '../types'
import { buildNotebookDependencyGraph } from './notebookNodeContent'

describe('buildNotebookDependencyGraph', () => {
    const sqlV2Node = (nodeId: string, returnVariable: string, code: string): Record<string, unknown> => ({
        type: NotebookNodeType.SQLV2,
        attrs: { nodeId, returnVariable, code },
    })

    it('links a SQLV2 node to a downstream SQLV2 node that references it by table name', () => {
        // The "Used in" back-links depend on SQLV2 producing an export and its reader listing it as a use.
        const content = {
            type: 'doc',
            content: [sqlV2Node('a', 'df1', 'select id from events'), sqlV2Node('b', 'joined', 'select * from df1')],
        }
        const graph = buildNotebookDependencyGraph(content)
        expect(graph.downstreamUsageByNode['a'].df1.map((usage) => usage.nodeId)).toEqual(['b'])
        expect(graph.upstreamSourcesByNode['b'].df1.nodeId).toEqual('a')
    })
})
