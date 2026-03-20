import { NodeKind } from '~/queries/schema/schema-general'

import { getExecutedQueryTabLabel } from './QueryTabs'

describe('getExecutedQueryTabLabel', () => {
    it('keeps the clickhouse label for regular HogQL queries', () => {
        expect(
            getExecutedQueryTabLabel({
                kind: NodeKind.HogQLQuery,
                query: 'SELECT 1',
            })
        ).toEqual('Clickhouse')
    })

    it('shows raw sql for direct-source HogQL queries', () => {
        expect(
            getExecutedQueryTabLabel({
                kind: NodeKind.HogQLQuery,
                query: 'SELECT 1',
                connectionId: 'postgres-connection-id',
            })
        ).toEqual('Raw SQL')
    })

    it('shows raw sql when a data table wraps a direct-source HogQL query', () => {
        expect(
            getExecutedQueryTabLabel({
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: 'SELECT 1',
                    connectionId: 'postgres-connection-id',
                },
            } as any)
        ).toEqual('Raw SQL')
    })
})
