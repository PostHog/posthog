import { parseMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'
import { NotebookComponentProps } from 'lib/components/MarkdownNotebook/types'

import { buildMarkdownNotebookContent, getMarkdownNotebookMarkdown } from '../markdownNotebookV2'
import { convertLegacyCodeCellsInContent } from './convertLegacyCodeCellsInContent'

function convertMarkdown(markdown: string): string {
    const content = buildMarkdownNotebookContent(markdown).content ?? []
    return getMarkdownNotebookMarkdown({ type: 'doc', content: convertLegacyCodeCellsInContent(content) })
}

function componentProps(markdown: string): { tagName: string; props: NotebookComponentProps }[] {
    return parseMarkdownNotebook(markdown).nodes.flatMap((node) =>
        node.type === 'component' ? [{ tagName: node.tagName, props: node.props }] : []
    )
}

describe('convertLegacyCodeCellsInContent', () => {
    test.each([
        {
            scenario: 'a Python cell keeps its code and title and drops the execution state',
            markdown: `<Python nodeId="py-1" title="Cleanup" code="print(1)" globalsUsed={["df"]} pythonExecution={{"status":"ok","stdout":"1"}} pythonExecutionCodeHash={42} />`,
            expected: [
                {
                    tagName: 'PythonV2',
                    props: { nodeId: 'py-1', code: 'print(1)', showFilters: true, title: 'Cleanup' },
                },
            ],
        },
        {
            scenario: 'an unnamed DuckDB cell is written out with the name downstream cells referenced',
            markdown: `<DuckSQL nodeId="duck-1" code="select 1" duckExecution={{"status":"ok"}} />`,
            expected: [
                {
                    tagName: 'SQLV2',
                    props: { nodeId: 'duck-1', code: 'select 1', showFilters: true, returnVariable: 'duck_df' },
                },
            ],
        },
        {
            scenario: 'a named HogQL cell keeps its own name',
            markdown: `<HogQLSQL nodeId="hogql-1" code="select 1" returnVariable="events_df" />`,
            expected: [
                {
                    tagName: 'SQLV2',
                    props: { nodeId: 'hogql-1', code: 'select 1', showFilters: true, returnVariable: 'events_df' },
                },
            ],
        },
    ])('$scenario', ({ markdown, expected }) => {
        expect(componentProps(convertMarkdown(markdown))).toEqual(expected)
    })

    it('gives a cell without a persisted nodeId the same durable id on every migration', () => {
        const markdown = `<Python code="print(1)" />`
        const [cell] = componentProps(convertMarkdown(markdown))

        expect(cell.tagName).toBe('PythonV2')
        expect(typeof cell.props.nodeId).toBe('string')
        expect(cell.props.nodeId).not.toBe('')
        // Nothing saves the migrated markdown until the author edits, so two loads (or two clients)
        // must mint the same id. A random one orphans a run dispatched under the previous load.
        expect(componentProps(convertMarkdown(markdown))[0].props.nodeId).toBe(cell.props.nodeId)
    })

    it('leaves the markdown byte-identical when there is no legacy cell', () => {
        const markdown = `# Title\n\n\n<SQLV2 nodeId="sql-1" code="select 1" />\n\n\nSome  text with   odd spacing`

        expect(convertMarkdown(markdown)).toBe(markdown)
    })

    it('keeps the surrounding blocks when only one cell is converted', () => {
        const markdown = `# Title\n\n\n<Python nodeId="py-1" code="print(1)" />\n\n\n<PythonV2 nodeId="py-2" code="print(2)" />`

        const converted = convertMarkdown(markdown)

        expect(converted).toContain('# Title')
        expect(componentProps(converted).map((cell) => cell.tagName)).toEqual(['PythonV2', 'PythonV2'])
        expect(componentProps(converted)[1].props).toEqual({ nodeId: 'py-2', code: 'print(2)' })
    })
})
