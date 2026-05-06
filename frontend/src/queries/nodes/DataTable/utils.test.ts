import {
    defaultDataTableEventColumns,
    defaultDataTablePersonColumns,
    extractAsAlias,
    extractDisplayLabel,
    extractExpressionComment,
    getColumnsForQuery,
    getDefaultDataTablePersonColumns,
    orderByForSelectKey,
    removeAsAlias,
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
        // Double-quoted aliases (HogQL grammar treats double quotes as quoted identifier delimiters)
        [`properties.$city AS "City Name"`, 'City Name'],
        [
            `formatDateTime(toTimeZone(timestamp, 'Europe/Berlin'), '%b %d, %H:%i:%s') as "Absolute Time"`,
            'Absolute Time',
        ],
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

    describe('ColumnConfigurator setColumns should not leak stale columns', () => {
        it.each([
            ['EventsQuery', NodeKind.EventsQuery],
            ['SessionsQuery', NodeKind.SessionsQuery],
        ])('strips stale columns for %s so getColumnsForQuery reads source.select', (_, sourceKind) => {
            const query: DataTableNode = {
                kind: NodeKind.DataTableNode,
                columns: defaultDataTableEventColumns,
                source: { kind: sourceKind, select: defaultDataTableEventColumns } as any,
            }

            const { columns: _discard, ...queryWithoutColumns } = query
            const result = {
                ...queryWithoutColumns,
                source: { ...query.source, select: ['*', 'event'] },
            } as DataTableNode

            expect(result).not.toHaveProperty('columns')
            expect(getColumnsForQuery(result)).toEqual(['*', 'event'])
        })

        it('preserves columns for HogQL queries', () => {
            const result: DataTableNode = {
                kind: NodeKind.DataTableNode,
                columns: ['*', 'event', 'timestamp'],
                source: { kind: NodeKind.HogQLQuery, query: 'SELECT *' },
            }

            expect(getColumnsForQuery(result)).toEqual(['*', 'event', 'timestamp'])
        })
    })

    describe('removeAsAlias', () => {
        it.each([
            // No alias — return as-is
            ['timestamp', 'timestamp'],
            ['event', 'event'],
            ['properties.$lib', 'properties.$lib'],
            ['coalesce(a, b)', 'coalesce(a, b)'],
            // Bare-word alias
            ['properties.$browser AS Browser', 'properties.$browser'],
            ['properties.$browser as browser', 'properties.$browser'],
            // Backtick alias
            ['properties.$city AS `City Name`', 'properties.$city'],
            // Double-quoted alias (the reported user case)
            [
                `formatDateTime(toTimeZone(timestamp, 'Europe/Berlin'), '%b %d, %H:%i:%s') as "Absolute Time"`,
                `formatDateTime(toTimeZone(timestamp, 'Europe/Berlin'), '%b %d, %H:%i:%s')`,
            ],
            // AS followed by trailing comment
            ['x AS foo -- bar', 'x'],
            // AS inside string literal — only outermost trailing AS stripped
            [`replaceAll(x, ' as ', '_') AS cleaned`, `replaceAll(x, ' as ', '_')`],
            // Empty / falsy
            ['', ''],
        ])('removeAsAlias(%p) = %p', (input, expected) => {
            expect(removeAsAlias(input)).toBe(expected)
        })
    })

    describe('orderByForSelectKey', () => {
        const userExpression = `formatDateTime(toTimeZone(timestamp, 'Europe/Berlin'), '%b %d, %H:%i:%s') as "Absolute Time"`
        const userExpressionBare = `formatDateTime(toTimeZone(timestamp, 'Europe/Berlin'), '%b %d, %H:%i:%s')`

        it('resolves a key matching a raw select entry directly (bare identifier path)', () => {
            expect(orderByForSelectKey('properties.$lib', ['*', 'event', 'properties.$lib', 'timestamp'])).toBe(
                'properties.$lib'
            )
        })

        it('resolves a key that is the resolved alias name to the underlying expression (the reported bug)', () => {
            expect(orderByForSelectKey('Absolute Time', ['*', 'event', userExpression, 'timestamp'])).toBe(
                userExpressionBare
            )
        })

        it('resolves a key matching a backtick-aliased expression', () => {
            expect(orderByForSelectKey('City Name', ['properties.$city AS `City Name`'])).toBe('properties.$city')
        })

        it('falls back to the key (with AS stripped) when no select entry matches', () => {
            expect(orderByForSelectKey('event', [])).toBe('event')
            expect(orderByForSelectKey('Absolute Time', [])).toBe('Absolute Time')
        })

        it('returns the raw key when select contains the same string (no AS clause)', () => {
            expect(orderByForSelectKey('timestamp', ['timestamp', 'event'])).toBe('timestamp')
        })
    })
})
