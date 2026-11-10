import { groupNotebookColumns, getColumnWidths, resizeNotebookColumns, NotebookColumnsGroup } from './columnLayout'
import { getMarkdownNotebookVisualGroups } from './documentModel'
import { parseMarkdownNotebook, serializeMarkdownNotebook } from './markdown'

const markdown = `# Review

<Columns widths={[2,1]}>

<Column>

## Acquisition

Notes for the first chart.

<Query nodeId="first-chart" query={{"kind":"SavedInsightNode","shortId":"demo-first"}} />

</Column>

<Column>

Second column notes.

<Query nodeId="second-chart" query={{"kind":"SavedInsightNode","shortId":"demo-second"}} />

</Column>

</Columns>

Full-width conclusion.`

describe('notebook columns', () => {
    it('round-trips explicit text and chart membership without hiding inner blocks', () => {
        const document = parseMarkdownNotebook(markdown)
        expect(document.errors).toEqual([])
        expect(serializeMarkdownNotebook(document)).toEqual(markdown)
        const groups = groupNotebookColumns(getMarkdownNotebookVisualGroups(document.nodes))
        expect(groups.map((group) => group.type)).toEqual(['text', 'columns', 'text'])
        const layout = groups[1] as NotebookColumnsGroup
        expect(layout.columns.map((column) => column.groups.map((group) => group.type))).toEqual([
            ['text', 'block'],
            ['text', 'block'],
        ])
        expect(layout.columns[0].groups[1]).toMatchObject({ node: { props: { nodeId: 'first-chart' } } })
        expect(layout.columns[1].groups[1]).toMatchObject({ node: { props: { nodeId: 'second-chart' } } })
    })

    it('adds empty columns and preserves every content block and id when reducing the count', () => {
        const document = parseMarkdownNotebook(markdown)
        const layout = groupNotebookColumns(getMarkdownNotebookVisualGroups(document.nodes))[1] as NotebookColumnsGroup
        const expanded = resizeNotebookColumns(document.nodes, layout, 4)
        const expandedLayout = groupNotebookColumns(
            getMarkdownNotebookVisualGroups(expanded)
        )[1] as NotebookColumnsGroup
        expect(expandedLayout.columns).toHaveLength(4)
        const extraContent = expandedLayout.columns[3].groups[0]
        expect(extraContent.type).toBe('text')
        if (extraContent.type !== 'text') {
            throw new Error('Expected an editable paragraph in the new column')
        }
        extraContent.items[0].node = {
            ...extraContent.items[0].node,
            type: 'paragraph',
            children: [{ type: 'text', text: 'Keep this note.' }],
        }
        const populated = expanded.map((node) =>
            node.id === extraContent.items[0].node.id ? extraContent.items[0].node : node
        )
        const reduced = resizeNotebookColumns(populated, expandedLayout, 2)
        const reducedLayout = groupNotebookColumns(getMarkdownNotebookVisualGroups(reduced))[1] as NotebookColumnsGroup
        expect(reducedLayout.columns).toHaveLength(2)
        expect(reduced).toContainEqual(extraContent.items[0].node)
        expect(
            reduced.filter((node) => node.type !== 'component' || !['Column', 'ColumnEnd'].includes(node.tagName))
        ).toEqual(
            populated
                .filter((node) => node.type !== 'component' || !['Column', 'ColumnEnd'].includes(node.tagName))
                .map((node) => (node.id === layout.start.node.id ? reducedLayout.start.node : node))
        )
        expect(serializeMarkdownNotebook({ ...document, nodes: reduced })).toContain('Keep this note.')
    })

    it.each([
        markdown.replace('</Columns>', ''),
        markdown.replace('</Column>', ''),
        markdown.replace('<Column>', '<Column>\n\n<Columns>'),
    ])('keeps malformed layout content visible at full width', (source) => {
        const groups = getMarkdownNotebookVisualGroups(parseMarkdownNotebook(source).nodes)
        expect(groupNotebookColumns(groups)).toEqual(groups)
    })

    it('does not interpret layout tags inside code fences', () => {
        const source = '```jsx\n<Columns>\n<Column>\nExample\n</Column>\n</Columns>\n```'
        const document = parseMarkdownNotebook(source)
        expect(document.nodes).toHaveLength(1)
        expect(document.nodes[0].type).toBe('code')
        expect(serializeMarkdownNotebook(document)).toBe(source)
    })

    it.each([
        [{ widths: [2, 1] }, [2, 1]],
        [{ widths: [0, -1, '2', null] }, [1, 1]],
        [{ widths: [Number.NaN, Number.POSITIVE_INFINITY] }, [1, 1]],
        [{ widths: [100000] }, [1, 1]],
        [{}, [1, 1]],
    ])('bounds width values before generating CSS: %j', (props, expected) => {
        expect(getColumnWidths(props, 2)).toEqual(expected)
    })
})
