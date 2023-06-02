import {
    defaultDataTableEventColumns,
    defaultDataTablePersonColumns,
    extractCommentOrAlias,
    getColumnsForQuery,
    removeCommentOrAlias,
} from '~/queries/nodes/DataTable/utils'
import { NodeKind } from '~/queries/schema'

describe('DataTable utils', () => {
    it('extractCommentOrAlias', () => {
        expect(extractCommentOrAlias('')).toBe('')
        expect(extractCommentOrAlias('asd -- bla')).toBe('bla')
        expect(extractCommentOrAlias('asd -- asd --   bla  ')).toBe('bla')
        expect(extractCommentOrAlias('asd as `hello`')).toBe('hello')
        expect(extractCommentOrAlias('asd as "hello world"')).toBe('hello world')
        expect(extractCommentOrAlias('asd as $bandana')).toBe('$bandana')
    })

    it('removeCommentOrAlias', () => {
        expect(removeCommentOrAlias('')).toBe('')
        expect(removeCommentOrAlias('asd -- bla')).toBe('asd')
        expect(removeCommentOrAlias('asd -- asd --   bla  ')).toBe('asd -- asd')
        expect(removeCommentOrAlias(' hoho trim  -- trim')).toBe('hoho trim')
        expect(removeCommentOrAlias('asd as `hello`')).toBe('asd')
        expect(removeCommentOrAlias('asd as "hello world"')).toBe('asd')
        expect(removeCommentOrAlias('asd as $bandana')).toBe('asd')
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
