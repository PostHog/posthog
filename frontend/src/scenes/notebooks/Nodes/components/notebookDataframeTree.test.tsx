import { NotebookKernelFrame } from '../../Notebook/notebookKernelInfoLogic'
import { buildDataframeTreeSection } from './notebookDataframeTree'

describe('buildDataframeTreeSection', () => {
    const frames: NotebookKernelFrame[] = [
        { name: 'sql_df', kind: 'frame', columns: [['event', 'VARCHAR']], row_count: 3 },
        { name: 'agg', kind: 'table', columns: [['total', 'BIGINT']], row_count: 1 },
    ]

    const names = (searchTerm: string): string[] =>
        buildDataframeTreeSection(frames, searchTerm)[0]?.children?.map((child) => child.name) ?? []

    it('has no section without a live kernel', () => {
        // No kernel means nothing local is SELECT-able, so an empty "Dataframes" folder would be
        // claiming the notebook has none rather than that there is nowhere to look.
        expect(buildDataframeTreeSection([], '')).toEqual([])
    })

    it.each([
        ['', ['sql_df', 'agg']],
        ['ag', ['agg']],
        // Columns match too — the same affordance the warehouse tree gives for a table's fields.
        ['event', ['sql_df']],
        ['nope', []],
    ])("filters to the tree's own search term %p", (searchTerm, expected) => {
        // The tree swaps in its filtered data while searching, so a section that ignored the term
        // would sit above the results still listing everything.
        expect(names(searchTerm)).toEqual(expected)
    })

    it('reports row counts the tree can render natively', () => {
        // QueryDatabase reads record.row_count to render the count beside the name; drop it and
        // dataframes silently lose the shape info that makes the panel worth opening.
        const [section] = buildDataframeTreeSection(frames, '')
        expect(section.children?.map((child) => child.record?.row_count)).toEqual([3, 1])
    })
})
