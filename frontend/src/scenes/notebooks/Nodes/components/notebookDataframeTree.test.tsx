import { NotebookKernelFrame } from '../../Notebook/notebookKernelInfoLogic'
import { NotebookFrameNodeSummary } from '../notebookNodeContent'
import { buildDataframeTreeSection } from './notebookDataframeTree'

describe('buildDataframeTreeSection', () => {
    const sqlNode = (name: string, hasRun = true): NotebookFrameNodeSummary => ({
        nodeId: `n-${name}`,
        name,
        nodeType: 'sql',
        columns: hasRun ? [['id', 'String']] : [],
        rowCount: hasRun ? 50 : null,
        hasRun,
    })
    const pythonNode = (name: string, hasRun = true): NotebookFrameNodeSummary => ({
        nodeId: `n-${name}`,
        name,
        nodeType: 'python',
        columns: hasRun ? [['count', 'int64']] : [],
        rowCount: hasRun ? 3 : null,
        hasRun,
    })
    const kernelFrame = (name: string, kind: NotebookKernelFrame['kind'] = 'frame'): NotebookKernelFrame => ({
        name,
        kind,
        columns: [['a', 'BIGINT']],
        row_count: 7,
    })

    const children = (section: ReturnType<typeof buildDataframeTreeSection>): [string, string | undefined][] =>
        (section[0]?.children ?? []).map((child) => [child.name, child.disabledReason])

    it('lists a SQL frame the kernel has never seen', () => {
        // The bug this shipped with: a SQL cell's output lives in ClickHouse and only enters the
        // kernel if something materializes it, but it is referenceable from SQL the whole time.
        // Sourcing the list from the kernel alone hid it entirely.
        expect(children(buildDataframeTreeSection([sqlNode('events_df')], [], ''))).toEqual([['events_df', undefined]])
    })

    it('greys out a python frame the kernel no longer has, but never a SQL one', () => {
        // A python frame only ever exists in the kernel, so absence means it is really gone. The
        // same absence for a SQL frame means nothing, so the two must not be treated alike.
        expect(children(buildDataframeTreeSection([sqlNode('events_df'), pythonNode('top50_people')], [], ''))).toEqual(
            [
                ['events_df', undefined],
                ['top50_people', 'Not in the kernel right now — run this cell to make it available'],
            ]
        )
    })

    it.each([
        ['sql', sqlNode('never_ran', false)],
        ['python', pythonNode('never_ran', false)],
    ])('greys out an un-run %s cell', (_nodeType, node) => {
        // No successful run means nothing to reference: the backend resolves refs to the latest
        // DONE run and treats a node without one as not-run.
        expect(children(buildDataframeTreeSection([node], [], ''))).toEqual([
            ['never_ran', 'Run this cell to make it available'],
        ])
    })

    it('shows a materialized frame once, with the kernel shape', () => {
        // A SQL frame a python cell pulled in is both a cell output and a kernel entry. It must
        // not double up, and the kernel's shape wins because it is the current one.
        const section = buildDataframeTreeSection([sqlNode('people')], [kernelFrame('people')], '')
        expect(children(section)).toEqual([['people', undefined]])
        expect(section[0].children?.[0].record?.row_count).toEqual(7)
    })

    it('lists a DuckDB table no cell binds', () => {
        // A CREATE TABLE in a DuckDB cell writes no result file and appears nowhere in the
        // document — the kernel's catalog is the only place it exists.
        expect(children(buildDataframeTreeSection([], [kernelFrame('agg', 'table')], ''))).toEqual([['agg', undefined]])
    })

    it('has no section when there is nothing to list', () => {
        expect(buildDataframeTreeSection([], [], '')).toEqual([])
    })

    it.each([
        ['', ['events_df', 'agg']],
        ['ev', ['events_df']],
        // Columns match too — the same affordance the warehouse tree gives for a table's fields.
        ['id', ['events_df']],
        ['nope', []],
    ])("filters to the tree's own search term %p", (searchTerm, expected) => {
        // The tree swaps in its filtered data while searching, so a section that ignored the term
        // would sit above the results still listing everything.
        const section = buildDataframeTreeSection([sqlNode('events_df')], [kernelFrame('agg', 'table')], searchTerm)
        expect(children(section).map(([name]) => name)).toEqual(expected)
    })
})
