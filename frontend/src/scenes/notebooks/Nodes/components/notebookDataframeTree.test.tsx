import { NotebookKernelFrame } from '../../Notebook/notebookKernelInfoLogic'
import { NotebookFrameNodeSummary } from '../notebookNodeContent'
import { buildDataframeTreeSection } from './notebookDataframeTree'

describe('buildDataframeTreeSection', () => {
    const sqlNode = (name: string, hasRun = true, code = 'SELECT 1'): NotebookFrameNodeSummary => ({
        nodeId: `n-${name}`,
        name,
        nodeType: 'sql',
        columns: hasRun ? [['id', 'String']] : [],
        rowCount: hasRun ? 50 : null,
        hasRun,
        code,
    })
    const pythonNode = (name: string, hasRun = true, code = 'df = 1'): NotebookFrameNodeSummary => ({
        nodeId: `n-${name}`,
        name,
        nodeType: 'python',
        columns: hasRun ? [['count', 'int64']] : [],
        rowCount: hasRun ? 3 : null,
        hasRun,
        code,
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
        expect(children(buildDataframeTreeSection([sqlNode('events_df')], []))).toEqual([['events_df', undefined]])
    })

    it('greys out a python frame the kernel no longer has, but never a SQL one', () => {
        // A python frame only ever exists in the kernel, so absence means it is really gone. The
        // same absence for a SQL frame means nothing, so the two must not be treated alike.
        expect(children(buildDataframeTreeSection([sqlNode('events_df'), pythonNode('top50_people')], []))).toEqual([
            ['events_df', undefined],
            ['top50_people', 'Not in the kernel right now. Run the cell that creates it to make it available'],
        ])
    })

    it.each([
        ['sql', sqlNode('never_ran', false)],
        ['python', pythonNode('never_ran', false)],
    ])('greys out an un-run %s cell', (_nodeType, node) => {
        // No successful run means nothing to reference: the backend resolves refs to the latest
        // DONE run and treats a node without one as not-run.
        expect(children(buildDataframeTreeSection([node], []))).toEqual([
            ['never_ran', 'Run the cell that creates it to make it available'],
        ])
    })

    it('shows a materialized frame once, with the kernel shape', () => {
        // A SQL frame a python cell pulled in is both a cell output and a kernel entry. It must
        // not double up, and the kernel's shape wins because it is the current one.
        const section = buildDataframeTreeSection([sqlNode('people')], [kernelFrame('people')])
        expect(children(section)).toEqual([['people', undefined]])
        expect(section[0].children?.[0].record?.row_count).toEqual(7)
    })

    it('lists a DuckDB table no cell binds', () => {
        // A CREATE TABLE in a DuckDB cell writes no result file and appears nowhere in the
        // document — the kernel's catalog is the only place it exists.
        expect(children(buildDataframeTreeSection([], [kernelFrame('agg', 'table')]))).toEqual([['agg', undefined]])
    })

    it('collapses duplicate names, keeping the last', () => {
        // Python names are deliberately not disambiguated and default to `df`, so two un-run
        // Python cells is enough to emit `df` twice — duplicate ids in a virtualized tree.
        const section = buildDataframeTreeSection([pythonNode('df'), pythonNode('df')], [])
        expect(children(section)).toHaveLength(1)
        const ids = (section[0].children ?? []).map((c) => c.id)
        expect(new Set(ids).size).toEqual(ids.length)
    })

    it('has no section when there is nothing to list', () => {
        expect(buildDataframeTreeSection([], [])).toEqual([])
    })

    it('ignores an empty cell nobody has written yet', () => {
        // A blank cell takes the default returnVariable, so it collides with the first one and is
        // renamed sql_df_2 — listing it means every new cell adds a greyed-out row for a frame
        // the user never conceived of.
        const section = buildDataframeTreeSection([sqlNode('sql_df'), sqlNode('sql_df_2', false, '')], [])
        expect(children(section)).toEqual([['sql_df', undefined]])
    })

    it('says a cell that ran but bound nothing produced no dataframe', () => {
        // It has a result with no columns: its code binds no frame. "Run this cell" would be a
        // lie — it ran, and running it again changes nothing.
        const ranEmpty: NotebookFrameNodeSummary = {
            nodeId: 'n-new-df',
            name: 'new-df',
            nodeType: 'python',
            columns: [],
            rowCount: 0,
            hasRun: true,
            code: 'top50 = people.value_counts()',
        }
        expect(children(buildDataframeTreeSection([ranEmpty], []))).toEqual([
            ['new-df', "The last run of the cell that creates it didn't produce a dataframe"],
        ])
    })

    it('still lists a written cell that has not run', () => {
        // Written but un-run is a real intent to bind that name, so it stays with a nudge to run.
        const section = buildDataframeTreeSection([sqlNode('draft', false, 'SELECT 1')], [])
        expect(children(section)).toEqual([['draft', 'Run the cell that creates it to make it available']])
    })
})
