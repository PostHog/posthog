import { getContextColumn } from '~/queries/nodes/DataTable/renderColumn'
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
