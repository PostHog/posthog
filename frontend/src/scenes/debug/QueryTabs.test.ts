import { DataTableNode, HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import { getExecutedQueryTabLabel } from './QueryTabs'

describe('getExecutedQueryTabLabel', () => {
    it('keeps the clickhouse label for regular HogQL queries', () => {
        const query: HogQLQuery = {
            kind: NodeKind.HogQLQuery,
            query: 'SELECT 1',
        }

        expect(getExecutedQueryTabLabel(query)).toEqual('Clickhouse')
    })

    it('shows raw sql for direct-source HogQL queries', () => {
        const query: HogQLQuery = {
            kind: NodeKind.HogQLQuery,
            query: 'SELECT 1',
            connectionId: 'postgres-connection-id',
        }

        expect(getExecutedQueryTabLabel(query)).toEqual('Raw SQL')
    })

    it('shows raw sql when a data table wraps a direct-source HogQL query', () => {
        const query: DataTableNode = {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'SELECT 1',
                connectionId: 'postgres-connection-id',
            },
        }

        expect(getExecutedQueryTabLabel(query)).toEqual('Raw SQL')
    })
})
