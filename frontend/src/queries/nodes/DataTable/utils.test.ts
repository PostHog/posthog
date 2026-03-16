import {
    defaultDataTableEventColumns,
    defaultDataTablePersonColumns,
    extractAsAlias,
    extractDisplayLabel,
    extractExpressionComment,
    getColumnsForQuery,
    getDefaultDataTablePersonColumns,
    removeExpressionComment,
} from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

describe('DataTable utils', () => {
    it('extractExpressionComment', () => {
        expect(extractExpressionComment('')).toBe('')
        expect(extractExpressionComment('asd -- bla')).toBe('bla')
        expect(extractExpressionComment('asd -- asd --   bla  ')).toBe('bla')
    })

    it.each([
        // Basic AS alias (case insensitive)
        ['properties.$browser AS Browser', 'Browser'],
        ['properties.$browser as browser', 'browser'],
        ['properties.$browser As Mixed', 'Mixed'],
        // Backtick aliases with spaces
        ['properties.$city AS `City Name`', 'City Name'],
        ['toUpper(x) as `My Display Name`', 'My Display Name'],
        // Complex expressions
        ["coalesce(properties.$city, 'Unknown') AS City", 'City'],
        ['arrayJoin(properties.$active_feature_flags) AS flag', 'flag'],
        // AS inside string literal should still match final AS
        ["replaceAll(x, ' as ', '_') AS cleaned", 'cleaned'],
        // Nested AS - takes outermost/last
        ['if(x as y, 1, 0) AS result', 'result'],
        // Unicode aliases
        ['x AS città', 'città'],
        // No alias - returns null
        ['properties.$browser', null],
        ['coalesce(a, b)', null],
        // Malformed - returns null
        ['x AS', null],
        ['x AS ', null],
    ])('extractAsAlias(%s) = %s', (input, expected) => {
        expect(extractAsAlias(input)).toBe(expected)
    })

    it.each([
        // AS alias takes priority
        ['properties.$browser AS Browser', 'Browser'],
        // Falls back to comment syntax
        ['asd -- bla', 'bla'],
        // AS alias when no comment
        ['x AS foo', 'foo'],
        // AS alias takes priority over comment when both present
        ['x AS foo -- bar', 'foo'],
        // No alias or comment - returns original
        ['properties.$browser', 'properties.$browser'],
    ])('extractDisplayLabel(%s) = %s', (input, expected) => {
        expect(extractDisplayLabel(input)).toBe(expected)
    })

    it('removeExpressionComment', () => {
        expect(removeExpressionComment('')).toBe('')
        expect(removeExpressionComment('asd -- bla')).toBe('asd')
        expect(removeExpressionComment('asd -- asd --   bla  ')).toBe('asd -- asd')
        expect(removeExpressionComment(' hoho trim  -- trim')).toBe('hoho trim')
    })

    it('defaultDataTablePersonColumns does not include last_seen_at', () => {
        expect(defaultDataTablePersonColumns).not.toContain('last_seen_at')
    })

    it('getDefaultDataTablePersonColumns includes last_seen_at when enabled', () => {
        expect(getDefaultDataTablePersonColumns(true)).toContain('last_seen_at')
    })

    it('getDefaultDataTablePersonColumns excludes last_seen_at when disabled', () => {
        expect(getDefaultDataTablePersonColumns(false)).not.toContain('last_seen_at')
    })

    it('getColumnsForQuery', () => {
        // default columns if none given
        expect(
            getColumnsForQuery({
                kind: NodeKind.DataTableNode,
                source: { kind: NodeKind.EventsQuery, select: null as any },
            })
        ).toEqual(defaultDataTableEventColumns)

        // override with "columns"
        expect(
            getColumnsForQuery({
                kind: NodeKind.DataTableNode,
                columns: ['event'],
                source: { kind: NodeKind.EventsQuery, select: null as any },
            })
        ).toEqual(['event'])

        // otherwise use "select"
        expect(
            getColumnsForQuery({
                kind: NodeKind.DataTableNode,
                source: { kind: NodeKind.EventsQuery, select: ['*', 'properties.$current_url', 'event'] },
            })
        ).toEqual(['*', 'properties.$current_url', 'event'])

        // PersonsNode
        expect(
            getColumnsForQuery({
                kind: NodeKind.DataTableNode,
                source: { kind: NodeKind.PersonsNode },
            })
        ).toEqual(defaultDataTablePersonColumns)

        // "columns" takes precedence over "source.select"
        expect(
            getColumnsForQuery({
                kind: NodeKind.DataTableNode,
                columns: ['*', 'event', 'timestamp'],
                source: { kind: NodeKind.EventsQuery, select: ['*', 'event'] },
            })
        ).toEqual(['*', 'event', 'timestamp'])

        // without "columns", falls through to "source.select"
        expect(
            getColumnsForQuery({
                kind: NodeKind.DataTableNode,
                source: { kind: NodeKind.EventsQuery, select: ['*', 'event'] },
            })
        ).toEqual(['*', 'event'])
    })

    describe('ColumnConfigurator setColumns callback should not leak stale columns', () => {
        // Simulates the setColumns callback from ColumnConfigurator.tsx.
        // The callback receives `query` (queryWithDefaults) which may contain a
        // stale top-level `columns` field. For query types that use source.select,
        // the callback must strip `columns` so getColumnsForQuery reads source.select.
        const buildSetColumnsResult = (query: DataTableNode, newColumns: string[]): DataTableNode => {
            const allColumns = ['*', ...newColumns]
            const { columns: _discard, ...queryWithoutColumns } = query
            if (query.source.kind === NodeKind.EventsQuery || query.source.kind === NodeKind.SessionsQuery) {
                return {
                    ...queryWithoutColumns,
                    source: { ...query.source, select: allColumns },
                } as DataTableNode
            } else if (query.source.kind === NodeKind.ActorsQuery || query.source.kind === NodeKind.GroupsQuery) {
                return {
                    ...queryWithoutColumns,
                    source: { ...query.source, select: allColumns },
                } as DataTableNode
            }
            return { ...query, columns: allColumns }
        }

        it.each([
            ['EventsQuery', NodeKind.EventsQuery],
            ['SessionsQuery', NodeKind.SessionsQuery],
        ])('strips stale columns for %s', (_, sourceKind) => {
            const queryWithStaleColumns: DataTableNode = {
                kind: NodeKind.DataTableNode,
                columns: defaultDataTableEventColumns,
                source: { kind: sourceKind, select: defaultDataTableEventColumns } as any,
            }

            const result = buildSetColumnsResult(queryWithStaleColumns, ['event'])

            expect(result).not.toHaveProperty('columns')
            expect(getColumnsForQuery(result)).toEqual(['*', 'event'])
        })

        it('preserves columns for HogQL queries', () => {
            const query: DataTableNode = {
                kind: NodeKind.DataTableNode,
                columns: ['*', 'event'],
                source: { kind: NodeKind.HogQLQuery, query: 'SELECT *' },
            }

            const result = buildSetColumnsResult(query, ['event', 'timestamp'])

            expect(result).toHaveProperty('columns', ['*', 'event', 'timestamp'])
        })
    })
})
