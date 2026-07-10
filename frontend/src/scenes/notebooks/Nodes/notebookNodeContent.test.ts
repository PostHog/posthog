import { buildMarkdownNotebookContent, serializeMarkdownNotebookComponent } from '../Notebook/markdownNotebookV2'
import { NotebookNodeType } from '../types'
import { buildNotebookDependencyGraph, extractPythonIdentifiers } from './notebookNodeContent'

describe('buildNotebookDependencyGraph', () => {
    const sqlV2Node = (nodeId: string, returnVariable: string, code: string): Record<string, unknown> => ({
        type: NotebookNodeType.SQLV2,
        attrs: { nodeId, returnVariable, code },
    })

    const pythonV2Node = (nodeId: string, returnVariable: string, code: string): Record<string, unknown> => ({
        type: NotebookNodeType.PythonV2,
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

    it('links PythonV2 cells in both directions (python reads sql, sql joins the python frame)', () => {
        // Journey 10 staleness walks these edges: without PythonV2 in the graph, running a
        // SQL cell never marks its Python dependents stale, and vice versa.
        const content = {
            type: 'doc',
            content: [
                sqlV2Node('a', 'sql_df', 'select id from events'),
                pythonV2Node('py', 'new_events', 'new_events = sql_df.head(50)'),
                sqlV2Node('c', 'joined', 'select * from new_events'),
            ],
        }
        const graph = buildNotebookDependencyGraph(content)
        expect(graph.downstreamUsageByNode['a'].sql_df.map((usage) => usage.nodeId)).toEqual(['py'])
        expect(graph.upstreamSourcesByNode['py'].sql_df.nodeId).toEqual('a')
        expect(graph.downstreamUsageByNode['py'].new_events.map((usage) => usage.nodeId)).toEqual(['c'])
    })

    it('links PythonV2 cells held inside a markdown notebook', () => {
        // Markdown notebooks are the only V2 surface; without expanding PythonV2 tags the
        // graph misses every real-world Python cell.
        const markdown = [
            serializeMarkdownNotebookComponent('SQLV2', {
                nodeId: 'a',
                returnVariable: 'sql_df',
                code: 'select id from events',
            }),
            serializeMarkdownNotebookComponent('PythonV2', {
                nodeId: 'py',
                returnVariable: 'new_events',
                code: 'new_events = sql_df.head()',
            }),
        ].join('\n\n')
        const graph = buildNotebookDependencyGraph(buildMarkdownNotebookContent(markdown))
        expect(graph.downstreamUsageByNode['a'].sql_df.map((usage) => usage.nodeId)).toEqual(['py'])
    })

    it('extractPythonIdentifiers ignores strings, comments, and attribute tails', () => {
        // A frame name inside a string or after a dot is not a read; matching it would
        // create a false dependency edge and mark unrelated cells stale.
        const identifiers = extractPythonIdentifiers(
            'result = sql_df.head(10)  # other_df is just a comment\nprint("other_df")\nlabel = frame.other_df'
        )
        expect(identifiers).toEqual(expect.arrayContaining(['result', 'sql_df', 'print', 'label', 'frame']))
        expect(identifiers).not.toContain('other_df')
        expect(identifiers).not.toContain('head')
    })

    it('links an InputV2 widget to the cells that read its variable', () => {
        // Journey 11: changing a widget must find its dependents to re-run; without the
        // widget in the graph the change applies to the kernel but nothing refreshes.
        const content = {
            type: 'doc',
            content: [
                { type: NotebookNodeType.InputV2, attrs: { nodeId: 'w', variable: 'date_from' } },
                pythonV2Node('py', 'filtered', 'filtered = df[df.date >= date_from]'),
            ],
        }
        const graph = buildNotebookDependencyGraph(content)
        expect(graph.downstreamUsageByNode['w'].date_from.map((usage) => usage.nodeId)).toEqual(['py'])
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
