import { NodeKind } from '~/queries/schema'
import { Query } from './Query'

interface SQLTableProps {
    query: string
}

export function SQLTable({ query }: SQLTableProps): JSX.Element {
    return <Query query={{ kind: NodeKind.DataTableNode, source: { kind: NodeKind.HogQLQuery, query: query } }} />
}
