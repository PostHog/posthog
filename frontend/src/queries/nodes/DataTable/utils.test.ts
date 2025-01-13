import {
    defaultDataTableEventColumns,
    defaultDataTablePersonColumns,
    extractExpressionComment,
    getColumnsForQuery,
    removeExpressionComment,
} from '~/queries/nodes/DataTable/utils'
import { NodeKind } from '~/queries/schema/schema-general'

describe('DataTable utils', () => {
    it('extractExpressionComment', () => {
        expect(extractExpressionComment('')).toBe('')
        expect(extractExpressionComment('asd -- bla')).toBe('bla')
        expect(extractExpressionComment('asd -- asd --   bla  ')).toBe('bla')
    })

    it('removeExpressionComment', () => {
        expect(removeExpressionComment('')).toBe('')
        expect(removeExpressionComment('asd -- bla')).toBe('asd')
        expect(removeExpressionComment('asd -- asd --   bla  ')).toBe('asd -- asd')
        expect(removeExpressionComment(' hoho trim  -- trim')).toBe('hoho trim')
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
    })
})
