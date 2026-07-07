import { buildMarkdownNotebookContent, serializeMarkdownNotebookComponent } from '../Notebook/markdownNotebookV2'
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

    it('disambiguates two nodes that share a return variable so a reference links to only the first', () => {
        // Without the uniquification pass both nodes would export `sql_df` and `from sql_df`
        // would ambiguously attribute to both; the second node's export becomes `sql_df_2`.
        const content = {
            type: 'doc',
            content: [
                sqlV2Node('a', 'sql_df', 'select id from events'),
                sqlV2Node('b', 'sql_df', 'select id from persons'),
                sqlV2Node('c', 'joined', 'select * from sql_df'),
            ],
        }
        const graph = buildNotebookDependencyGraph(content)
        expect(graph.nodesById['b'].exports).toEqual(['sql_df_2'])
        expect(graph.downstreamUsageByNode['a'].sql_df.map((usage) => usage.nodeId)).toEqual(['c'])
        expect(graph.upstreamSourcesByNode['c'].sql_df.nodeId).toEqual('a')
    })

    it('links SQLV2 cells inside a markdown notebook', () => {
        // Markdown notebooks hold cells as tags inside one markdown attribute; without
        // expanding them the graph is empty and the "Used in" back-links never render.
        const markdown = [
            serializeMarkdownNotebookComponent('SQLV2', {
                nodeId: 'a',
                returnVariable: 'df1',
                code: 'select id from events',
            }),
            serializeMarkdownNotebookComponent('SQLV2', {
                nodeId: 'b',
                returnVariable: 'joined',
                code: 'select * from df1',
            }),
        ].join('\n\n')
        const graph = buildNotebookDependencyGraph(buildMarkdownNotebookContent(markdown))
        expect(graph.downstreamUsageByNode['a'].df1.map((usage) => usage.nodeId)).toEqual(['b'])
        expect(graph.upstreamSourcesByNode['b'].df1.nodeId).toEqual('a')
    })
})
