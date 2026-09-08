import { getContextColumn, renderColumn } from '~/queries/nodes/DataTable/renderColumn'
import { renderColumnMeta } from '~/queries/nodes/DataTable/renderColumnMeta'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { QueryContextColumn } from '~/queries/types'

describe('getContextColumn', () => {
    const columns: Record<string, QueryContextColumn> = {
        campaign: { title: 'Campaign' },
    }

    it('resolves a context column key', () => {
        const result = getContextColumn('context.columns.campaign', columns)
        expect(result.queryContextColumnName).toBe('campaign')
        expect(result.queryContextColumn).toBe(columns.campaign)
    })

    // A column list built from an unnamed conversion goal can contain a non-string
    // entry; the lookup must not throw, or one bad column crashes the whole table.
    it.each([undefined, null, 42])('tolerates a non-string key: %p', (key) => {
        const result = getContextColumn(key as unknown as string, columns)
        expect(result.queryContextColumnName).toBeUndefined()
        expect(result.queryContextColumn).toBeUndefined()
    })
})

describe('renderColumnMeta', () => {
    const query: DataTableNode = {
        kind: NodeKind.DataTableNode,
        source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
    }

    // getContextColumn is not the only string-method call on a column key: column meta is built
    // for every surviving key too. A non-string key must return empty meta instead of throwing.
    it.each([undefined, null, 42])('tolerates a non-string key: %p', (key) => {
        expect(() => renderColumnMeta(key as unknown as string, query)).not.toThrow()
        expect(renderColumnMeta(key as unknown as string, query)).toEqual({})
    })
})

describe('renderColumn', () => {
    // Not a HogQL query: HogQL keys take a separate branch that never calls key.startsWith. A
    // marketing-analytics-style query reaches the context.columns / $virt_mrr branches, which are
    // where a non-string key used to crash the render pass.
    const query = {
        kind: NodeKind.DataTableNode,
        source: { kind: NodeKind.EventsQuery, select: [] },
    } as unknown as DataTableNode

    // A gap column (e.g. from an unnamed conversion goal) puts a non-string key into the list.
    // renderColumn must render the value defensively instead of throwing and crashing the table.
    it.each([undefined, null, 42])('tolerates a non-string key: %p', (key) => {
        expect(() => renderColumn(key as unknown as string, 42, [], 0, 1, query)).not.toThrow()
        expect(renderColumn(key as unknown as string, 42, [], 0, 1, query)).toBe('42')
    })
})
