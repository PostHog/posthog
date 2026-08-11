import type { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'

import type { AccountSortOrder } from './accountsLogic'
import { sortAccountRows } from './accountsSort'

const COLUMNS = ['name', 'notebook_count', 'csm']

const buildRow = ({
    name,
    count = 0,
    csm = [],
}: {
    name: string
    count?: number | null
    csm?: number[]
}): DataTableRow => ({
    result: [{ name, external_id: name, id: name }, count, csm],
})

const cellAt = (row: DataTableRow, index: number): unknown => (row.result as unknown[])[index]
const names = (rows: DataTableRow[]): string[] => rows.map((r) => (cellAt(r, 0) as { name: string }).name)
const counts = (rows: DataTableRow[]): unknown[] => rows.map((r) => cellAt(r, 1))

describe('sortAccountRows', () => {
    it.each([
        ['there is no active sort', null as AccountSortOrder],
        ['the sorted column is not visible', { column: 'missing', direction: 'asc' } as AccountSortOrder],
    ])('returns the same rows untouched when %s', (_label, sortOrder) => {
        const rows = [buildRow({ name: 'B' }), buildRow({ name: 'A' })]
        expect(sortAccountRows(rows, sortOrder, COLUMNS)).toBe(rows)
    })

    it('sorts the name tuple column by its name, case-insensitively, in both directions', () => {
        const rows = [buildRow({ name: 'Charlie' }), buildRow({ name: 'alpha' }), buildRow({ name: 'Bravo' })]
        expect(names(sortAccountRows(rows, { column: 'name', direction: 'asc' }, COLUMNS))).toEqual([
            'alpha',
            'Bravo',
            'Charlie',
        ])
        expect(names(sortAccountRows(rows, { column: 'name', direction: 'desc' }, COLUMNS))).toEqual([
            'Charlie',
            'Bravo',
            'alpha',
        ])
    })

    it('sorts a numeric column numerically, not lexically', () => {
        const rows = [
            buildRow({ name: 'a', count: 2 }),
            buildRow({ name: 'b', count: 10 }),
            buildRow({ name: 'c', count: 1 }),
        ]
        expect(counts(sortAccountRows(rows, { column: 'notebook_count', direction: 'asc' }, COLUMNS))).toEqual([
            1, 2, 10,
        ])
    })

    it.each([['asc'], ['desc']] as const)('always sorts empty cells last when %s', (direction) => {
        const rows = [
            buildRow({ name: 'a', count: null }),
            buildRow({ name: 'b', count: 5 }),
            buildRow({ name: 'c', count: null }),
        ]
        expect(counts(sortAccountRows(rows, { column: 'notebook_count', direction }, COLUMNS))).toEqual([5, null, null])
    })

    it('treats an empty relationship array as an empty cell (sorts last)', () => {
        const rows = [buildRow({ name: 'unassigned', csm: [] }), buildRow({ name: 'assigned', csm: [42] })]
        expect(names(sortAccountRows(rows, { column: 'csm', direction: 'asc' }, COLUMNS))).toEqual([
            'assigned',
            'unassigned',
        ])
    })

    it('keeps equal-keyed rows in their incoming order (stable)', () => {
        const rows = [
            buildRow({ name: 'first', count: 5 }),
            buildRow({ name: 'second', count: 5 }),
            buildRow({ name: 'third', count: 5 }),
        ]
        expect(names(sortAccountRows(rows, { column: 'notebook_count', direction: 'asc' }, COLUMNS))).toEqual([
            'first',
            'second',
            'third',
        ])
    })
})
