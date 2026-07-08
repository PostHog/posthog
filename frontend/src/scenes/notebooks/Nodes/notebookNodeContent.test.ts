import { buildMarkdownNotebookContent, serializeMarkdownNotebookComponent } from '../Notebook/markdownNotebookV2'
import { NotebookNodeType } from '../types'
import { buildNotebookDependencyGraph, collectLocalFrames } from './notebookNodeContent'

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

describe('collectLocalFrames', () => {
    it('collects SQL and Python cells from a markdown notebook in document order and parses run envelopes', () => {
        // The schema browser is empty (or shows frames out of order) if the markdown
        // expansion stops seeing both cell types in a single document-ordered pass.
        const markdown = [
            serializeMarkdownNotebookComponent('SQLV2', {
                nodeId: 'a',
                returnVariable: 'df1',
                code: 'select id from events',
                runId: 'run-1',
                result: { columns: ['id'], types: [['id', 'Int64']], row_count: 3, first_page: [[1], [2], [3]] },
            }),
            serializeMarkdownNotebookComponent('Python', {
                nodeId: 'b',
                returnVariable: 'pdf',
                code: 'pdf = df1.head()',
            }),
            serializeMarkdownNotebookComponent('SQLV2', {
                nodeId: 'c',
                returnVariable: 'joined',
                code: 'select * from df1',
            }),
        ].join('\n\n')

        const frames = collectLocalFrames(buildMarkdownNotebookContent(markdown))

        expect(frames.map((frame) => frame.nodeId)).toEqual(['a', 'b', 'c'])
        expect(frames[0]).toMatchObject({
            name: 'df1',
            nodeType: NotebookNodeType.SQLV2,
            runId: 'run-1',
            result: { columns: ['id'], types: [['id', 'Int64']], rowCount: 3, firstPage: [[1], [2], [3]] },
        })
        expect(frames[1]).toMatchObject({ name: 'pdf', nodeType: NotebookNodeType.Python, runId: null, result: null })
    })

    it('treats a run that produced no dataframe as a definition, not a frame', () => {
        // A Python cell that only printed to stdout persists an envelope with empty
        // columns; showing it as a frame with shape 0×0 would be wrong.
        const content = {
            type: 'doc',
            content: [
                {
                    type: NotebookNodeType.Python,
                    attrs: {
                        nodeId: 'a',
                        returnVariable: 'df',
                        code: 'print("hi")',
                        runId: 'run-1',
                        result: { columns: [], row_count: 0, first_page: [], stdout: 'hi\n' },
                    },
                },
            ],
        }
        expect(collectLocalFrames(content)[0].result).toBeNull()
    })

    it('disambiguates duplicate SQLV2 names like the dependency graph, but leaves Python names raw', () => {
        // SQLV2 names must match the cross-reference names the graph resolves;
        // Python names are the literal kernel variables (last-run-wins).
        const content = {
            type: 'doc',
            content: [
                { type: NotebookNodeType.SQLV2, attrs: { nodeId: 'a', returnVariable: 'sql_df', code: '' } },
                { type: NotebookNodeType.SQLV2, attrs: { nodeId: 'b', returnVariable: 'sql_df', code: '' } },
                { type: NotebookNodeType.Python, attrs: { nodeId: 'c', returnVariable: 'df', code: '' } },
                { type: NotebookNodeType.Python, attrs: { nodeId: 'd', returnVariable: 'df', code: '' } },
            ],
        }
        expect(collectLocalFrames(content).map((frame) => frame.name)).toEqual(['sql_df', 'sql_df_2', 'df', 'df'])
    })
})
